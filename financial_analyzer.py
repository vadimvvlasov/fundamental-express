import argparse
import os
import time
from dataclasses import dataclass
from datetime import datetime

# Resolve workspace root relative to this script file
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRATCH_DIR = os.path.join(SCRIPT_DIR, "scratch")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
os.makedirs(SCRATCH_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Try importing yfinance
try:
    import yfinance as yf

    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    Image,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# The express "sins" checklist in compute_metrics() is a two-tier model
# (see docs/spec/technical-implementation-spec.md Section 1):
#   - CRITICAL sins (fcf_negative, cr_below_1, lt_insolvency, equity_negative):
#     any single hit forces verdict = SKIP, regardless of everything else.
#   - MINOR sins: weighted 1.0/0.5/0.3 by how directly they reflect real
#     operating/cash health vs how noisy/paper-driven the metric is. Weights
#     sum to MAX_MINOR_SCORE and decide BUY/WATCH/SKIP when no critical sin
#     fired.


@dataclass
class Sin:
    """One fired checklist violation. `weight` is 0.0 for critical sins -
    weight is meaningless there since any single critical hit is decisive."""

    id: str
    tier: str  # "critical" | "minor"
    weight: float
    message: str


MINOR_SIN_WEIGHTS = {
    "equity_declining": 1.0,
    "fcf_declining": 1.0,
    "revenue_declining": 1.0,
    "operating_income_declining": 1.0,
    "cr_declining": 0.5,
    "gross_margin_declining": 0.5,
    "operating_margin_declining": 0.5,
    "net_income_declining": 0.3,
    "net_margin_declining": 0.3,
}
MAX_MINOR_SCORE = sum(MINOR_SIN_WEIGHTS.values())

# ── DESIGN PALETTE (Corporate Slate & Teal Archetype) ──────────────────
COLORS = {
    "heading": HexColor("#1E293B"),  # Deep Slate - titles & sections
    "body": HexColor("#334155"),  # Slate - readable text
    "accent": HexColor("#0F766E"),  # Teal - visual highlights/underlines
    "muted": HexColor("#64748B"),  # Slate gray - headers, page numbers
    "bg_alt": HexColor("#F8FAFC"),  # Off-white tint - tables, callouts
    "bg_header": HexColor("#0F766E"),  # Teal - table header backgrounds
    "white": HexColor("#FFFFFF"),
    "success": HexColor("#16A34A"),  # Green for positive indicators
    "danger": HexColor("#DC2626"),  # Red for warning flags
    "warning": HexColor("#D97706"),  # Amber for cautionary notes
}

# ── REGISTER UNICODE FONTS ──────────────────────────────────────────────
# We look for DejaVuSans because it natively supports Cyrillic characters.
try:
    pdfmetrics.registerFont(
        TTFont("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    )
    pdfmetrics.registerFont(
        TTFont(
            "DejaVuSans-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        )
    )
    pdfmetrics.registerFontFamily(
        "DejaVuSans", normal="DejaVuSans", bold="DejaVuSans-Bold"
    )
    FONT_NAME = "DejaVuSans"
    FONT_BOLD = "DejaVuSans-Bold"
except Exception as e:
    print(
        f"Warning: Could not register DejaVuSans font: {e}. Falling back to standard Helvetica."
    )
    FONT_NAME = "Helvetica"
    FONT_BOLD = "Helvetica-Bold"

# ── PAGE GEOMETRY ───────────────────────────────────────────────────────
PAGE_SIZE = LETTER
MARGIN = 0.75 * inch  # 54pt for clean layout and compact tables
PAGE_W, PAGE_H = PAGE_SIZE
USABLE_W = PAGE_W - 2 * MARGIN


# ── HELPER: ESCAPE XML SYMBOLS FOR PARAGRAPH ────────────────────────────
def escape_xml(val):
    if not isinstance(val, str):
        val = str(val)
    return val.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── ROBUST FINANCIAL ROW LOCATOR ────────────────────────────────────────
def find_row(df, keywords, default_val=0.0):
    """Find a financial statement row by keyword.

    Exact matches across ALL keywords are tried before ANY partial match.
    yfinance's row order commonly puts lines like "Reconciled Cost Of
    Revenue" ahead of "Total Revenue" - checking exact matches per-keyword
    before moving on (the old behavior) let a "revenue" partial match grab
    the cost-of-revenue row before "total revenue" ever got its exact-match
    turn, silently corrupting margin/revenue-trend numbers downstream.
    """
    for kw in keywords:
        for idx in df.index:
            if kw.lower() == idx.lower():
                return df.loc[idx]
    for kw in keywords:
        for idx in df.index:
            if kw.lower() in idx.lower():
                return df.loc[idx]
    # Return series of zeros with same columns
    return pd.Series([default_val] * len(df.columns), index=df.columns)


# ── ERRORS ───────────────────────────────────────────────────────────────
class DataUnavailableError(Exception):
    """Raised when real market data could not be fetched after retries.

    We never silently substitute mock numbers for a real ticker analysis -
    that produces a plausible-looking PDF full of numbers that belong to
    nobody. Callers either handle this (retry later, tell the user) or let
    it propagate.
    """

    def __init__(self, ticker, attempts):
        super().__init__(
            f"Could not fetch real market data for '{ticker}' from Yahoo Finance "
            f"after {attempts} attempt(s). Yahoo Finance is often just flaky - "
            f"rerun in a minute or two."
        )
        self.ticker = ticker
        self.attempts = attempts


def _fx_rate(from_ccy, to_ccy):
    """USD-per-unit-of-from_ccy conversion rate, or None if it can't be fetched."""
    if from_ccy == to_ccy:
        return 1.0
    try:
        fx = yf.Ticker(f"{from_ccy}{to_ccy}=X")
        rate = fx.info.get("regularMarketPrice") or fx.info.get("previousClose")
        if rate:
            return float(rate)
    except Exception:
        pass
    return None


# ── FINANCIAL DATA COLLECTOR ────────────────────────────────────────────
def _fetch_once(ticker):
    """Single real-data fetch attempt. Returns a data dict, or None on any failure."""
    if not YFINANCE_AVAILABLE:
        return None
    try:
        ticker_obj = yf.Ticker(ticker)
        info = ticker_obj.info
        financials = ticker_obj.financials
        balance = ticker_obj.balance_sheet
        cashflow = ticker_obj.cashflow

        if financials.empty or balance.empty or cashflow.empty:
            return None

        if info.get("regularMarketPrice"):
            price, price_kind = info["regularMarketPrice"], "последняя сделка (regularMarketPrice)"
        elif info.get("currentPrice"):
            price, price_kind = info["currentPrice"], "последняя сделка (currentPrice)"
        elif info.get("previousClose"):
            price, price_kind = info["previousClose"], "цена предыдущего закрытия (previousClose)"
        else:
            price, price_kind = None, None
        shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
        if not price or not shares:
            return None

        # regularMarketTime is a real exchange timestamp for the quote above;
        # fall back to "now" (script run time) only if yfinance omits it, and
        # say so plainly rather than implying it's a market timestamp.
        market_time_epoch = info.get("regularMarketTime")
        exchange_tz = info.get("exchangeTimezoneName")
        if market_time_epoch:
            from datetime import timezone as _tz
            quote_time = datetime.fromtimestamp(market_time_epoch, tz=_tz.utc)
            if exchange_tz:
                try:
                    from zoneinfo import ZoneInfo
                    quote_time = quote_time.astimezone(ZoneInfo(exchange_tz))
                except Exception:
                    pass
            quote_time_label = quote_time.strftime("%Y-%m-%d %H:%M %Z")
        else:
            quote_time_label = f"{datetime.now().strftime('%Y-%m-%d %H:%M')} (время запуска скрипта, не биржевое время)"

        beta = info.get("beta") or 1.1
        name = info.get("longName") or info.get("shortName") or ticker

        # Foreign issuers (e.g. TSM/TSMC) often report financial statements in
        # their home currency (TWD) while price/shares/market cap are quoted in
        # USD via the ADR. Mixing the two without converting corrupts every
        # dollar figure downstream (DCF fair value, fundamentals table) even
        # though ratio-based checks (current ratio, margins, YoY trends) stay
        # correct since they compare same-currency figures.
        financial_ccy = info.get("financialCurrency")
        trading_ccy = info.get("currency") or "USD"
        fx_rate = 1.0
        if financial_ccy and financial_ccy != trading_ccy:
            fx_rate = _fx_rate(financial_ccy, trading_ccy)
            if fx_rate is None:
                return None  # can't safely mix currencies - treat like any other fetch failure

        return {
            "ticker": ticker.upper(),
            "name": name,
            "price": float(price),
            "shares": int(shares),
            "beta": float(beta),
            "financials": financials,
            "balance": balance,
            "cashflow": cashflow,
            "is_sample": False,
            "price_kind": price_kind,
            "quote_time_label": quote_time_label,
            "fx_rate": fx_rate,
            "financial_currency": financial_ccy or trading_ccy,
            "trading_currency": trading_ccy,
            # Raw info payload, kept only for the Forward Outlook section
            # (forwardPE/pegRatio/earningsGrowth/revenueGrowth) - never used
            # by compute_metrics()'s core sins/DCF logic.
            "info": info,
        }
    except Exception as e:
        print(f"  [{ticker}] fetch attempt failed: {e}")
        return None


def _sample_data(ticker):
    years = ["2021", "2022", "2023", "2024"]

    fin_data = {
        "Total Revenue": [365817000000, 394328000000, 383285000000, 391035000000],
        "Operating Income": [108949000000, 119437000000, 114301000000, 117823000000],
        "Net Income": [94680000000, 99803000000, 96995000000, 100913000000],
        "Diluted EPS": [5.61, 6.11, 6.13, 6.43],
    }
    financials_df = pd.DataFrame(fin_data, index=years).T

    bal_data = {
        "Total Current Assets": [134836000000, 135405000000, 143566000000, 149200000000],
        "Total Current Liabilities": [125481000000, 153982000000, 145308000000, 140000000000],
        "Total Assets": [351002000000, 352755000000, 352581000000, 365000000000],
        "Total Liabilities Net Minority Interest": [287912000000, 302083000000, 290437000000, 295000000000],
        "Goodwill": [0, 0, 0, 0],
        "Stockholders Equity": [63090000000, 50672000000, 62144000000, 70000000000],
        "Total Debt": [124719000000, 120069000000, 111088000000, 105000000000],
        "Cash And Cash Equivalents": [34940000000, 23646000000, 29965000000, 31000000000],
    }
    balance_df = pd.DataFrame(bal_data, index=years).T

    cf_data = {
        "Free Cash Flow": [92953000000, 111443000000, 99584000000, 104000000000],
        "Operating Cash Flow": [104038000000, 122151000000, 110574000000, 115000000000],
    }
    cashflow_df = pd.DataFrame(cf_data, index=years).T

    return {
        "ticker": ticker.upper(),
        "name": "Apple Inc. (Sample)" if ticker.upper() == "AAPL" else f"{ticker.upper()} (SAMPLE - NOT REAL DATA)",
        "price": 180.0,
        "shares": 15000000000,
        "beta": 1.1,
        "financials": financials_df,
        "balance": balance_df,
        "cashflow": cashflow_df,
        "is_sample": True,
        "price_kind": "SAMPLE - НЕ РЕАЛЬНАЯ ЦЕНА",
        "quote_time_label": f"{datetime.now().strftime('%Y-%m-%d %H:%M')} (время запуска скрипта на SAMPLE-данных)",
        "fx_rate": 1.0,
        "financial_currency": "USD",
        "trading_currency": "USD",
        # No real consensus data for sample runs - compute_forward_outlook
        # falls through its whole chain to the Trailing P/E / Historical FCF
        # CAGR proxies (both computable from the sample data itself) rather
        # than crashing on a missing info dict.
        "info": {},
    }


def get_company_data(ticker, retries=5, retry_delay=5, allow_sample=False):
    """Fetch real financials for `ticker` from Yahoo Finance.

    Yahoo Finance is flaky (connection resets, timeouts, occasional empty
    responses) - most failures clear up on a retry a few seconds later, so
    we retry before giving up. By default this NEVER falls back to mock
    data: it raises DataUnavailableError so callers don't mistake a demo
    number for a real one. Pass allow_sample=True only for demos.
    """
    for attempt in range(1, retries + 1):
        data = _fetch_once(ticker)
        if data is not None:
            return data
        if attempt < retries:
            print(
                f"  [{ticker}] real data unavailable (attempt {attempt}/{retries}), "
                f"retrying in {retry_delay}s..."
            )
            time.sleep(retry_delay)

    if allow_sample:
        print(
            f"Warning: no real data for {ticker} after {retries} attempts - "
            f"using SAMPLE data (--allow-sample set). These numbers are NOT real."
        )
        return _sample_data(ticker)

    raise DataUnavailableError(ticker, retries)


# ── FLOWABLE: SECTION DIVIDER ──────────────────────────────────────────
class SectionDivider(Flowable):
    def __init__(self, width, color):
        Flowable.__init__(self)
        self._width = width
        self.color = color
        self._height = 20

    def wrap(self, availWidth, availHeight):
        return self._width, self._height

    def draw(self):
        y = self._height / 2
        self.canv.setStrokeColor(self.color)
        self.canv.setLineWidth(1.2)
        self.canv.line(0, y, self._width, y)


# ── FLOWABLE: CALLOUT BOX ──────────────────────────────────────────────
class CalloutBox(Flowable):
    def __init__(self, text, width, colors, body_style, bar_color=None):
        Flowable.__init__(self)
        self._width = width
        self.colors = colors
        self.bar_color = bar_color or colors["accent"]
        self.bar_w = 6
        self.pad = 10
        inner_w = self._width - self.bar_w - 2 * self.pad
        self._para = Paragraph(text, body_style)
        self._para_w, self._para_h = self._para.wrap(inner_w, 10000)
        self._height = self._para_h + 2 * self.pad

    def wrap(self, availWidth, availHeight):
        return self._width, self._height

    def draw(self):
        self.canv.setFillColor(self.colors["bg_alt"])
        self.canv.rect(0, 0, self._width, self._height, fill=1, stroke=0)
        self.canv.setFillColor(self.bar_color)
        self.canv.rect(0, 0, self.bar_w, self._height, fill=1, stroke=0)
        self._para.drawOn(self.canv, self.bar_w + self.pad, self.pad)


# ── GENERATE EXCEL-STYLE TABLES WITH PARAGRAPHCELLS ────────────────────
def create_reportlab_table(headers, rows, styles, colors, col_widths=None):
    header_style = ParagraphStyle(
        "TableHead",
        fontName=FONT_BOLD,
        fontSize=9,
        textColor=colors["white"],
        leading=11,
    )
    cell_style = ParagraphStyle(
        "TableCell",
        fontName=FONT_NAME,
        fontSize=8.5,
        textColor=colors["body"],
        leading=11,
    )

    header_row = [Paragraph(escape_xml(h), header_style) for h in headers]
    data_rows = []
    for r in rows:
        data_rows.append([Paragraph(escape_xml(str(cell)), cell_style) for cell in r])

    t = Table([header_row] + data_rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors["bg_header"]),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors["white"], colors["bg_alt"]],
                ),
                ("GRID", (0, 0), (-1, -1), 0.5, colors["muted"]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return t


# ── CHART GENERATOR ─────────────────────────────────────────────────────
def generate_fcf_chart(years, hist_fcf, proj_years, proj_fcf, ticker):
    fig, ax = plt.subplots(figsize=(7, 3))

    fig.patch.set_facecolor("white")
    ax.set_facecolor("#F8FAFC")

    hist_x = list(range(len(years)))
    ax.bar(
        hist_x,
        [val / 1e9 for val in hist_fcf],
        color="#0F766E",
        label="Исторический FCF",
        width=0.4,
    )

    proj_x = list(range(len(years), len(years) + len(proj_years)))
    ax.bar(
        proj_x,
        [val / 1e9 for val in proj_fcf],
        color="#0284C7",
        label="Прогнозный FCF",
        width=0.4,
    )

    ax.set_title(
        f"Свободный денежный поток (FCF) компании {ticker} (в млрд. USD)",
        fontsize=10,
        fontweight="bold",
        color="#1E293B",
    )
    all_years = list(years) + [f"Y{i}" for i in proj_years]
    ax.set_xticks(range(len(all_years)))
    ax.set_xticklabels(all_years, fontsize=8)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#64748B")
    ax.spines["bottom"].set_color("#64748B")
    ax.tick_params(colors="#334155", labelsize=8)
    ax.legend(frameon=True, facecolor="white", edgecolor="none", fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.3, color="#64748B")

    plt.tight_layout()
    chart_path = os.path.join(SCRATCH_DIR, f"{ticker}_fcf_chart.png")
    plt.savefig(chart_path, dpi=300, bbox_inches="tight")
    plt.close()
    return chart_path


# ── CORE ANALYSIS: EXPRESS "SINS" CHECKLIST + DCF ───────────────────────
def compute_metrics(data):
    """Run the express sins-checklist and the CAPM/DCF valuation on `data`.

    This is the single source of truth for both the per-company PDF report
    and the multi-company comparative tool - the two must never compute
    this differently.
    """
    df_fin = data["financials"]
    df_bal = data["balance"]
    df_cf = data["cashflow"]
    price = data["price"]
    shares = data["shares"]
    beta = data["beta"]

    years = list(df_fin.columns)
    try:
        years_sorted = sorted(years, key=lambda x: int(str(x).split("-")[0]))
        df_fin = df_fin[years_sorted]
        df_bal = df_bal[years_sorted]
        df_cf = df_cf[years_sorted]
        years = years_sorted
    except Exception:
        pass
    year_labels = [str(y).split("-")[0] for y in years]

    revenue = find_row(df_fin, ["revenue", "total revenue", "sales"])
    operating_income = find_row(df_fin, ["operating income", "operating profit", "ebit"])
    net_income = find_row(df_fin, ["net income", "net profit"])
    eps = find_row(df_fin, ["eps", "diluted eps", "basic eps"])

    revenue_cost = find_row(df_fin, ["cost of revenue"], default_val=float("nan"))

    curr_assets = find_row(df_bal, ["total current assets", "current assets"])
    curr_liab = find_row(df_bal, ["total current liabilities", "current liabilities"])
    total_assets = find_row(df_bal, ["total assets"])
    total_liab = find_row(df_bal, ["total liabilities"], default_val=float("nan"))
    goodwill = find_row(df_bal, ["goodwill"])
    equity = find_row(df_bal, ["stockholders equity", "total stockholders equity"])
    # "Total Debt" from yfinance bundles in capitalized lease obligations
    # (ASC 842) alongside interest-bearing debt. We treat interest-bearing
    # debt and lease liabilities as separate line items - "Долг" in this
    # report always means interest-bearing debt only (Long Term Debt),
    # never the lease-inclusive Total Debt figure, and we say so plainly
    # rather than inventing a blended "effective debt" number.
    interest_bearing_debt = find_row(df_bal, ["long term debt"], default_val=float("nan"))
    total_debt_incl_leases = find_row(df_bal, ["total debt"], default_val=float("nan"))
    lease_liabilities = find_row(
        df_bal, ["long term capital lease obligation", "capital lease obligations"],
        default_val=float("nan"),
    )
    debt = interest_bearing_debt if not interest_bearing_debt.isna().all() else total_debt_incl_leases
    cash = find_row(df_bal, ["cash and cash equivalents", "cash cash equivalents"])
    # yfinance sometimes exposes a pre-computed Net Debt row directly -
    # prefer that (it's whatever Yahoo's own methodology nets against cash)
    # over our own debt-minus-cash math when present, and label it
    # explicitly as "reported by Yahoo Finance" rather than implying our
    # own debt figure was the source.
    net_debt_reported = find_row(df_bal, ["net debt"], default_val=float("nan"))

    fcf = find_row(df_cf, ["free cash flow", "fcf"])

    # Convert monetary rows to the trading currency (e.g. TWD -> USD for TSM's
    # ADR) so they're comparable to price/shares, which are always quoted in
    # the trading currency. Ratio-based figures (current ratio, margins, share
    # counts, EPS) are left alone - EPS in particular is quoted per home-market
    # ordinary share, not per ADR, so currency conversion alone wouldn't make
    # it comparable to the ADR price anyway; that's a separate, undocumented
    # ADR-ratio issue we don't attempt to fix here.
    fx_rate = data.get("fx_rate", 1.0)
    if fx_rate != 1.0:
        revenue = revenue * fx_rate
        revenue_cost = revenue_cost * fx_rate
        operating_income = operating_income * fx_rate
        net_income = net_income * fx_rate
        curr_assets = curr_assets * fx_rate
        curr_liab = curr_liab * fx_rate
        total_assets = total_assets * fx_rate
        total_liab = total_liab * fx_rate
        goodwill = goodwill * fx_rate
        equity = equity * fx_rate
        debt = debt * fx_rate
        cash = cash * fx_rate
        fcf = fcf * fx_rate
        net_debt_reported = net_debt_reported * fx_rate
        lease_liabilities = lease_liabilities * fx_rate
        total_debt_incl_leases = total_debt_incl_leases * fx_rate

    curr_ratios = curr_assets / curr_liab
    net_margin = net_income / revenue * 100
    operating_margin = operating_income / revenue * 100
    # Gross margin needs Cost of Revenue, which is the exact field whose
    # substring collision with "Total Revenue" caused a real margin bug
    # earlier this session (see README). Only compute/check it when the row
    # was genuinely found - never silently divide by a zero-filled default.
    gross_margin = (
        (revenue - revenue_cost) / revenue * 100 if not revenue_cost.isna().all() else None
    )

    # Goodwill-adjusted long-term solvency: goodwill is a paper asset that
    # can't be sold/monetized in a liquidation, so it's excluded before
    # comparing long-term assets to long-term liabilities.
    long_term_assets_adj = (total_assets - curr_assets) - goodwill
    long_term_liab = (total_liab - curr_liab) if not total_liab.isna().all() else None

    # ── "Sins" checklist (express algorithm from the lecture, two-tier) ──
    sins = []

    latest_cr = curr_ratios.iloc[-1]
    if latest_cr < 1.0:
        sins.append(Sin(
            "cr_below_1", "critical", 0.0,
            f"Критическая ликвидность: коэффициент текущей ликвидности (Current Ratio) ниже 1.0 ({latest_cr:.2f}).",
        ))
    # A CR decline is only flagged if the company also isn't comfortably
    # liquid (CR >= 2.0) after the decline - dropping from, say, 4.0 to 3.0
    # isn't a red flag on its own. Requiring latest_cr >= 1.0 here keeps this
    # mutually exclusive with cr_below_1 above - a CR crash below 1.0 is
    # already captured as the critical sin and must not also double-count
    # as a minor "declining trend" sin on the same underlying fact.
    elif (
        len(curr_ratios) >= 2
        and curr_ratios.iloc[-1] < curr_ratios.iloc[-2]
        and latest_cr < 2.0
    ):
        sins.append(Sin(
            "cr_declining", "minor", MINOR_SIN_WEIGHTS["cr_declining"],
            f"Снижающийся тренд ликвидности: Current Ratio с {curr_ratios.iloc[-2]:.2f} до {curr_ratios.iloc[-1]:.2f}.",
        ))

    if long_term_liab is not None:
        latest_lt_assets = long_term_assets_adj.iloc[-1]
        latest_lt_liab = long_term_liab.iloc[-1]
        if latest_lt_assets < latest_lt_liab:
            sins.append(Sin(
                "lt_insolvency", "critical", 0.0,
                f"Долгосрочная неплатёжеспособность: скорректированные (за вычетом Goodwill) "
                f"долгосрочные активы ({latest_lt_assets / 1e6:,.0f} млн) меньше долгосрочных "
                f"обязательств ({latest_lt_liab / 1e6:,.0f} млн).",
            ))

    latest_equity = equity.iloc[-1]
    if latest_equity <= 0:
        sins.append(Sin(
            "equity_negative", "critical", 0.0,
            "Отрицательный акционерный капитал: обязательств больше, чем реальных активов.",
        ))
    elif len(equity) >= 2 and equity.iloc[-1] < equity.iloc[-2]:
        sins.append(Sin(
            "equity_declining", "minor", MINOR_SIN_WEIGHTS["equity_declining"],
            "Тренд падения капитала: Shareholder Equity снизился за последний год.",
        ))

    latest_fcf = fcf.iloc[-1]
    if latest_fcf <= 0:
        sins.append(Sin(
            "fcf_negative", "critical", 0.0,
            "Сжигание денежных средств: отрицательный Free Cash Flow.",
        ))
    elif len(fcf) >= 2 and fcf.iloc[-1] < fcf.iloc[-2]:
        sins.append(Sin(
            "fcf_declining", "minor", MINOR_SIN_WEIGHTS["fcf_declining"],
            "Падение денежного потока: снижение FCF за последний год.",
        ))

    if len(revenue) >= 2 and revenue.iloc[-1] < revenue.iloc[-2]:
        sins.append(Sin(
            "revenue_declining", "minor", MINOR_SIN_WEIGHTS["revenue_declining"],
            "Снижение выручки за последний год.",
        ))
    if len(operating_income) >= 2 and operating_income.iloc[-1] < operating_income.iloc[-2]:
        sins.append(Sin(
            "operating_income_declining", "minor", MINOR_SIN_WEIGHTS["operating_income_declining"],
            "Падение операционной прибыли за последний год.",
        ))
    if len(net_income) >= 2 and net_income.iloc[-1] < net_income.iloc[-2]:
        sins.append(Sin(
            "net_income_declining", "minor", MINOR_SIN_WEIGHTS["net_income_declining"],
            "Падение чистой прибыли за последний год.",
        ))
    if gross_margin is not None and len(gross_margin) >= 2 and gross_margin.iloc[-1] < gross_margin.iloc[-2]:
        sins.append(Sin(
            "gross_margin_declining", "minor", MINOR_SIN_WEIGHTS["gross_margin_declining"],
            f"Падение валовой маржи: Gross Margin с {gross_margin.iloc[-2]:.1f}% до {gross_margin.iloc[-1]:.1f}%.",
        ))
    if len(operating_margin) >= 2 and operating_margin.iloc[-1] < operating_margin.iloc[-2]:
        sins.append(Sin(
            "operating_margin_declining", "minor", MINOR_SIN_WEIGHTS["operating_margin_declining"],
            f"Падение операционной маржи: Operating Margin с {operating_margin.iloc[-2]:.1f}% до {operating_margin.iloc[-1]:.1f}%.",
        ))
    if len(net_margin) >= 2 and net_margin.iloc[-1] < net_margin.iloc[-2]:
        sins.append(Sin(
            "net_margin_declining", "minor", MINOR_SIN_WEIGHTS["net_margin_declining"],
            f"Падение рентабельности: чистая маржа с {net_margin.iloc[-2]:.1f}% до {net_margin.iloc[-1]:.1f}%.",
        ))

    critical_sins = [s for s in sins if s.tier == "critical"]
    minor_sins = [s for s in sins if s.tier == "minor"]
    minor_score = sum(s.weight for s in minor_sins)

    if critical_sins:
        verdict = "🔴 ПРОПУСТИТЬ / ВЫСОКИЙ РИСК"
        verdict_color_key = "danger"
        crit_labels = ", ".join(s.id for s in critical_sins)
        reasoning = (
            f"Обнаружен(ы) критический(е) фактор(ы) риска ({crit_labels}) — см. список ниже. "
            "Любой из них по отдельности делает инвестицию рискованной вне зависимости от прочих показателей."
        )
    elif minor_score <= 1.0:
        verdict = "🟢 КУПИТЬ / СИЛЬНЫЙ КАНДИДАТ"
        verdict_color_key = "success"
        reasoning = "Компания демонстрирует эталонную финансовую устойчивость, растущую выручку, отличную маржинальность и растущий свободный денежный поток. Риски минимальны."
    elif minor_score <= 2.5:
        verdict = "🟡 НАБЛЮДАТЬ / ОГРАНИЧЕННАЯ ДОЛЯ"
        verdict_color_key = "warning"
        reasoning = "Отличный сильный бизнес, однако в финансовых трендах присутствуют умеренные погрешности. Рекомендуется покупка только ограниченной долей."
    else:
        verdict = "🔴 ПРОПУСТИТЬ / ВЫСОКИЙ РИСК"
        verdict_color_key = "danger"
        reasoning = (
            f"Взвешенный балл второстепенных нарушений составил {minor_score:.1f} из {MAX_MINOR_SCORE:.1f} — "
            "см. список ниже. Совокупность этих факторов делает инвестицию рискованной на текущем этапе."
        )

    # ── DCF valuation (CAPM WACC) ───────────────────────────────────────
    fcf_values = fcf.values
    if len(fcf_values) >= 2 and fcf_values[0] > 0 and fcf_values[-1] > 0:
        cagr = (fcf_values[-1] / fcf_values[0]) ** (1 / (len(fcf_values) - 1)) - 1
        cagr = max(0.02, min(0.15, cagr))
    else:
        cagr = 0.05

    rf_rate = 0.04
    erp = 0.05
    cost_of_equity = rf_rate + beta * erp
    cost_of_debt = 0.045
    tax_rate = 0.21
    after_tax_debt = cost_of_debt * (1 - tax_rate)

    latest_debt = debt.iloc[-1]
    if pd.isna(latest_debt) or latest_debt < 0:
        latest_debt = 0.0

    market_cap = price * shares
    total_cap = market_cap + latest_debt
    if total_cap > 0:
        w_equity = market_cap / total_cap
        w_debt = latest_debt / total_cap
        wacc = (w_equity * cost_of_equity) + (w_debt * after_tax_debt)
    else:
        w_equity, w_debt = 1.0, 0.0
        wacc = 0.09
    wacc = max(0.05, min(0.15, wacc))

    proj_years = list(range(1, 6))
    fcf_latest = fcf_values[-1]
    projected_fcfs = []
    pv_fcfs = []
    for t in proj_years:
        future_fcf = fcf_latest * ((1 + cagr) ** t)
        pv_fcf = future_fcf / ((1 + wacc) ** t)
        projected_fcfs.append(future_fcf)
        pv_fcfs.append(pv_fcf)

    sum_pv_fcfs = sum(pv_fcfs)
    terminal_g = 0.025
    terminal_val = (
        projected_fcfs[-1] * (1 + terminal_g) / (wacc - terminal_g)
        if wacc > terminal_g
        else 0.0
    )
    pv_terminal_val = terminal_val / ((1 + wacc) ** 5)

    enterprise_value = sum_pv_fcfs + pv_terminal_val
    latest_cash = cash.iloc[-1] if not pd.isna(cash.iloc[-1]) else 0.0
    latest_net_debt_reported = (
        net_debt_reported.iloc[-1] if len(net_debt_reported) else float("nan")
    )
    latest_lease_liabilities = (
        lease_liabilities.iloc[-1] if len(lease_liabilities) else float("nan")
    )
    latest_total_debt_incl_leases = (
        total_debt_incl_leases.iloc[-1] if len(total_debt_incl_leases) else float("nan")
    )
    if not pd.isna(latest_net_debt_reported):
        # Use Yahoo Finance's own "Net Debt" line as-is - we never claim
        # it equals our own interest-bearing-debt-minus-cash figure, since
        # Yahoo's own methodology for that field isn't something we control
        # or can fully audit. We just report it as its own source.
        net_debt = latest_net_debt_reported
        net_debt_source = "reported"
    else:
        net_debt = latest_debt - latest_cash
        net_debt_source = "computed"
    equity_value = enterprise_value - net_debt
    fair_value_share = equity_value / shares if shares > 0 else 0.0

    over_under = (fair_value_share - price) / price * 100
    if over_under > 10.0:
        val_status = f"НЕДООЦЕНЕНА на {abs(over_under):.1f}% (Потенциал роста)"
        val_color_key = "success"
    elif over_under < -10.0:
        val_status = f"ПЕРЕОЦЕНЕНА на {abs(over_under):.1f}% (Завышенная стоимость)"
        val_color_key = "danger"
    else:
        val_status = f"ОЦЕНЕНА СПРАВЕДЛИВО (Отклонение {over_under:.1f}%)"
        val_color_key = "warning"

    wacc_variations = [wacc - 0.015, wacc - 0.0075, wacc, wacc + 0.0075, wacc + 0.015]
    growth_variations = [cagr - 0.02, cagr - 0.01, cagr, cagr + 0.01, cagr + 0.02]

    sensitivity_rows = []
    for g_v in growth_variations:
        row_vals = []
        for w_v in wacc_variations:
            if w_v <= terminal_g:
                row_vals.append("N/A")
                continue
            p_f_list = [fcf_latest * ((1 + g_v) ** t) for t in proj_years]
            pv_f_list = [p_f_list[t - 1] / ((1 + w_v) ** t) for t in proj_years]
            s_pv = sum(pv_f_list)
            t_v = p_f_list[-1] * (1 + terminal_g) / (w_v - terminal_g)
            pv_t_v = t_v / ((1 + w_v) ** 5)
            ev_v = s_pv + pv_t_v
            eq_v = ev_v - net_debt
            fv_s = eq_v / shares if shares > 0 else 0.0
            row_vals.append(f"{fv_s:.2f} USD")
        sensitivity_rows.append([f"g = {g_v * 100:.1f}%"] + row_vals)

    sensitivity_headers = ["г / WACC"] + [f"{w * 100:.2f}%" for w in wacc_variations]

    return {
        "year_labels": year_labels,
        "revenue": revenue,
        "operating_income": operating_income,
        "net_income": net_income,
        "eps": eps,
        "curr_assets": curr_assets,
        "curr_liab": curr_liab,
        "curr_ratios": curr_ratios,
        "equity": equity,
        "fcf": fcf,
        "net_margin": net_margin,
        "sins": sins,
        "critical_sins": critical_sins,
        "minor_sins": minor_sins,
        "minor_score": minor_score,
        "max_minor_score": MAX_MINOR_SCORE,
        "verdict": verdict,
        "verdict_color_key": verdict_color_key,
        "reasoning": reasoning,
        "beta": beta,
        "wacc": wacc,
        "cost_of_equity": cost_of_equity,
        "cost_of_debt_after_tax": after_tax_debt,
        "equity_weight": w_equity,
        "debt_weight": w_debt,
        "cagr": cagr,
        "proj_years": proj_years,
        "projected_fcfs": projected_fcfs,
        "pv_fcfs": pv_fcfs,
        "enterprise_value": enterprise_value,
        "net_debt": net_debt,
        "net_debt_source": net_debt_source,
        "interest_bearing_debt": latest_debt,
        "lease_liabilities": latest_lease_liabilities,
        "total_debt_incl_leases": latest_total_debt_incl_leases,
        "cash_balance": latest_cash,
        "equity_value": equity_value,
        "price": price,
        "fair_value_share": fair_value_share,
        "over_under_pct": over_under,
        "val_status": val_status,
        "val_color_key": val_color_key,
        "sensitivity_headers": sensitivity_headers,
        "sensitivity_rows": sensitivity_rows,
        "current_ratio": float(latest_cr),
        "net_margin_pct": float(net_margin.iloc[-1]) if not pd.isna(net_margin.iloc[-1]) else None,
    }


_EMPTY_FORWARD_OUTLOOK = {
    "forward_pe": None,
    "forward_pe_source": None,
    "growth_rate": None,
    "growth_pct": None,
    "growth_source": None,
    "peg_ratio": None,
    "peg_source": None,
}


def compute_forward_outlook(info, price, eps, historical_fcf_cagr):
    """Forward P/E, consensus growth, and PEG - a purely informational
    counterweight to the trailing-CAGR DCF, never fed into the Section 1
    verdict score (see docs/spec/technical-implementation-spec.md Section 2).

    yfinance's `.info` dict frequently has forwardPE/pegRatio/earningsGrowth/
    revenueGrowth as None for a given ticker, so every field runs through a
    fallback chain and is paired with a *_source label - the report must
    never imply a proxy is the real analyst consensus. This function never
    raises: any failure degrades to an all-N/A block, consistent with
    DataUnavailableError being reserved for the core financials fetch only.
    """
    try:
        info = info or {}
        latest_eps = eps.iloc[-1] if len(eps) else None
        trailing_pe = (
            price / latest_eps if latest_eps and latest_eps > 0 and price else None
        )

        forward_pe = info.get("forwardPE")
        forward_pe_source = "Forward P/E (Yahoo Finance)"
        if not forward_pe or forward_pe <= 0:
            forward_pe, forward_pe_source = trailing_pe, "Trailing P/E Proxy (форвардный P/E недоступен)"
        if not forward_pe or forward_pe <= 0:
            forward_pe, forward_pe_source = None, None

        growth_rate = info.get("earningsGrowth")
        growth_source = "Consensus Earnings Growth (Yahoo Finance)"
        if not growth_rate:
            growth_rate, growth_source = info.get("revenueGrowth"), "Consensus Revenue Growth (EPS growth недоступен)"
        if not growth_rate:
            growth_rate, growth_source = historical_fcf_cagr, "Historical FCF CAGR Proxy (консенсус недоступен)"
        if not growth_rate:
            growth_rate, growth_source = None, None

        # Yahoo's earningsGrowth/revenueGrowth are fractional (0.12 = +12%).
        # Known limitation: a >100% YoY growth fraction (e.g. 1.5 = +150%)
        # reads identically to an already-converted percentage under this
        # heuristic and would be mis-detected as "already a percent" -
        # accepted, same tolerance for imperfect heuristics on noisy
        # provider data as find_row's own exact-vs-partial matching.
        growth_pct = (
            growth_rate * 100 if growth_rate is not None and growth_rate < 1.0 else growth_rate
        )

        peg_ratio = info.get("pegRatio")
        peg_source = "PEG Ratio (Yahoo Finance)"
        if not peg_ratio or peg_ratio <= 0:
            peg_ratio, peg_source = info.get("trailingPegRatio"), "Trailing PEG (Yahoo Finance, форвардный PEG недоступен)"
        if (not peg_ratio or peg_ratio <= 0) and forward_pe and growth_pct:
            peg_ratio = forward_pe / growth_pct
            peg_source = "PEG Ratio (расчётный: Forward P/E ÷ Expected Growth %)"
        if not peg_ratio or peg_ratio <= 0:
            peg_ratio, peg_source = None, None

        return {
            "forward_pe": forward_pe,
            "forward_pe_source": forward_pe_source,
            "growth_rate": growth_rate,
            "growth_pct": growth_pct,
            "growth_source": growth_source,
            "peg_ratio": peg_ratio,
            "peg_source": peg_source,
        }
    except Exception as e:
        print(f"  Warning: forward outlook computation failed ({e}) - rendering N/A block.")
        return dict(_EMPTY_FORWARD_OUTLOOK)


def _peg_assessment(peg_ratio):
    """PEG color-coding for the Forward Outlook section (spec Section 2.4)."""
    if peg_ratio is None:
        return "muted", "Недостаточно данных"
    if peg_ratio < 1.0:
        return "success", "Недооценена с учетом роста"
    if peg_ratio <= 2.0:
        return "warning", "Оценена справедливо"
    return "danger", "Переоценена относительно роста"


def _fmt_or_na(value, fmt="{:.2f}"):
    return fmt.format(value) if value is not None else "N/A"


CATALYSTS_PLACEHOLDER = (
    "Катализаторы не указаны — заполните вручную перед принятием решения. "
    "Справедливая стоимость по DCF может не реализовываться рынком годами без триггера переоценки."
)


def resolve_catalysts_text(catalysts=None, catalysts_file=None):
    """Resolve the qualitative catalysts/risks text for report Section 5.

    Catalysts (product launches, regulatory shifts, reputational-crisis
    recovery) aren't fetchable data - they're an analyst's judgment call, so
    this never auto-generates or auto-fetches them. --catalysts and
    --catalysts-file are mutually exclusive - checked here, before any
    network call, so a bad CLI combo fails fast rather than after a slow
    Yahoo Finance round-trip. Neither given -> the mandatory
    methodology-reminder placeholder, never a fabricated catalyst.
    """
    if catalysts and catalysts_file:
        raise SystemExit("--catalysts and --catalysts-file are mutually exclusive")
    if catalysts_file:
        try:
            with open(catalysts_file, encoding="utf-8") as f:
                text = f.read().strip()
        except FileNotFoundError:
            raise SystemExit(f"--catalysts-file not found: {catalysts_file}")
        return text or CATALYSTS_PLACEHOLDER
    if catalysts:
        return catalysts.strip() or CATALYSTS_PLACEHOLDER
    return CATALYSTS_PLACEHOLDER


# ── MAIN PDF COMPILER ───────────────────────────────────────────────────
LEASE_ASSUMPTION_NOTE = (
    "Допущение по лизингу: в базовом DCF обязательства по аренде исключены из net debt, "
    "поскольку модель использует FCF после операционных арендных платежей. Это "
    "упрощающее допущение, а не универсальный бухгалтерский факт (выплаты по финансовой "
    "аренде могут классифицироваться иначе) - для сопоставлений, где lease liabilities "
    "рассматриваются как debt-like obligations, используйте альтернативный расчёт с "
    "Total Debt (включая аренду) вместо приведённого net debt."
)


def _debt_lines(m, trading_ccy):
    """Plain (label, value) pairs for the debt/net-debt disclosure - shared
    between the PDF and Markdown renderers so the two never drift apart.
    Never blends sources into a single invented number: each line names
    exactly where its figure comes from.
    """
    lines = [(
        "Долгосрочный долг (Long Term Debt, только процентный долг)",
        f"{m['interest_bearing_debt'] / 1e9:,.2f} млрд. {trading_ccy}",
    )]
    if not pd.isna(m["lease_liabilities"]):
        lines.append((
            "Долгосрочные обязательства по аренде (Long-term lease liability, исключены из net debt ниже)",
            f"{m['lease_liabilities'] / 1e9:,.2f} млрд. {trading_ccy}",
        ))
    if not pd.isna(m["total_debt_incl_leases"]):
        lines.append((
            "Total Debt (агрегированное поле провайдера данных, включает долг и debt-like "
            "обязательства по его классификации - может не равняться простой сумме строк "
            "выше; справочно, не используется в DCF)",
            f"{m['total_debt_incl_leases'] / 1e9:,.2f} млрд. {trading_ccy}",
        ))
    lines.append((
        "Денежные средства (Cash and Cash Equivalents)",
        f"{m['cash_balance'] / 1e9:,.2f} млрд. {trading_ccy}",
    ))
    net_debt_label = (
        "Чистый долг, использован в DCF (поле Net Debt из Yahoo Finance)"
        if m["net_debt_source"] == "reported"
        else "Чистый долг, использован в DCF (расчёт: Долгосрочный долг − Кэш)"
    )
    lines.append((net_debt_label, f"{m['net_debt'] / 1e9:,.2f} млрд. {trading_ccy}"))
    return lines


def build_markdown_report(ticker, data, m, forward_outlook=None, catalysts_text=None):
    """Plain-text/Markdown twin of the PDF report - same numbers, no charts."""
    name = data["name"]
    trading_ccy = data.get("trading_currency", "USD")
    financial_ccy = data.get("financial_currency", "USD")
    forward_outlook = forward_outlook or dict(_EMPTY_FORWARD_OUTLOOK)
    catalysts_text = catalysts_text or CATALYSTS_PLACEHOLDER
    catalysts_block = "\n".join(
        f"> {line}" if line.strip() else ">" for line in catalysts_text.splitlines()
    )
    fx_line = (
        f"> Отчётность в {financial_ccy}, конвертирована в {trading_ccy} по курсу "
        f"{data.get('fx_rate', 1.0):.4f}\n\n"
        if financial_ccy != trading_ccy else ""
    )
    year_labels = m["year_labels"]

    def row(label, series, fmt="{:,.1f}"):
        return f"| {label} | " + " | ".join(fmt.format(v) for v in series) + " |"

    if m["sins"]:
        sins_parts = []
        if m["critical_sins"]:
            sins_parts.append("**Критические:**\n" + "\n".join(f"- {s.message}" for s in m["critical_sins"]))
        if m["minor_sins"]:
            sins_parts.append(
                f"**Второстепенные (балл {m['minor_score']:.1f} из {m['max_minor_score']:.1f}):**\n"
                + "\n".join(f"- [{s.weight:.1f}] {s.message}" for s in m["minor_sins"])
            )
        sins_block = "\n\n".join(sins_parts)
    else:
        sins_block = "- Грехов не обнаружено."
    debt_block = "\n".join(f"- {label}: {value}" for label, value in _debt_lines(m, trading_ccy))
    sens_header = "| " + " | ".join(m["sensitivity_headers"]) + " |"
    sens_sep = "|" + "---|" * len(m["sensitivity_headers"])
    sens_rows = "\n".join("| " + " | ".join(r) + " |" for r in m["sensitivity_rows"])

    peg_color_key, peg_label = _peg_assessment(forward_outlook["peg_ratio"])
    peg_emoji = {"success": "🟢", "warning": "🟡", "danger": "🔴", "muted": "⚪"}[peg_color_key]
    forward_pe_txt = _fmt_or_na(forward_outlook["forward_pe"])
    growth_txt = _fmt_or_na(forward_outlook["growth_pct"], "{:.1f}%")
    peg_txt = _fmt_or_na(forward_outlook["peg_ratio"])

    md = f"""# Фундаментальный анализ & оценка DCF: {ticker.upper()}

Компания: **{name}** | Цена: **{m['price']:.2f} {trading_ccy}** ({data['price_kind']}, Yahoo Finance, {data['quote_time_label']})

{fx_line}## 1. Экспресс-вердикт и оценка рисков

**{m['verdict']}**

{m['reasoning']}

**Выявленные риски:**

{sins_block}

## 2. Экспресс-анализ финансовых результатов и баланса

Показатели в млн. {trading_ccy}.

| Показатель | {" | ".join(year_labels)} |
|---|{"---|" * len(year_labels)}
{row("Выручка (Revenue)", [v / 1e6 for v in m["revenue"]])}
{row("Операционная прибыль", [v / 1e6 for v in m["operating_income"]])}
{row("Чистая прибыль (Net Income)", [v / 1e6 for v in m["net_income"]])}
{row("Разводненная EPS, USD", list(m["eps"]), fmt="{:.2f}")}
{row("Оборотные активы", [v / 1e6 for v in m["curr_assets"]])}
{row("Краткосрочные обязательства", [v / 1e6 for v in m["curr_liab"]])}
{row("Current Ratio", list(m["curr_ratios"]), fmt="{:.2f}")}
{row("Акционерный капитал", [v / 1e6 for v in m["equity"]])}
{row("Free Cash Flow", [v / 1e6 for v in m["fcf"]])}

## 3. Модель дисконтирования денежных потоков (DCF)

- Стоимость собственного капитала (CAPM): Ke = 4% + β×5% = 4% + {m['beta']:.2f}×5% = {m['cost_of_equity'] * 100:.2f}%
- Стоимость долга после налога: Kd×(1-T) = 4.5%×(1-21%) = {m['cost_of_debt_after_tax'] * 100:.2f}% (Kd=4.5% и T=21% — фиксированные допущения методики, не специфичны для компании и не эффективная налоговая ставка компании)
- Веса структуры капитала (по рыночной капитализации): E/(D+E) = {m['equity_weight'] * 100:.1f}%, D/(D+E) = {m['debt_weight'] * 100:.1f}%
- **WACC:** {m['equity_weight'] * 100:.1f}%×{m['cost_of_equity'] * 100:.2f}% + {m['debt_weight'] * 100:.1f}%×{m['cost_of_debt_after_tax'] * 100:.2f}% = **{m['wacc'] * 100:.2f}%**
- CAGR роста FCF: {m['cagr'] * 100:.2f}% (историческая, ограничена 2-15%)
- Терминальный темп роста: 2.5%

{debt_block}

> {LEASE_ASSUMPTION_NOTE}

- Enterprise Value: {m['enterprise_value'] / 1e9:,.2f} млрд. {trading_ccy}
- Equity Value: {m['equity_value'] / 1e9:,.2f} млрд. {trading_ccy}

**Справедливая стоимость акции: {m['fair_value_share']:.2f} {trading_ccy}**
Последняя доступная рыночная котировка: {m['price']:.2f} {trading_ccy} ({data['price_kind']}, {data['quote_time_label']}) | Статус: **{m['val_status']}**

### Матрица чувствительности (г — рост явного 5-летнего прогноза FCF; терминальный рост фиксирован на 2.5% и используется только в формуле Гордона — условие WACC > g не требуется для этой матрицы)

{sens_header}
{sens_sep}
{sens_rows}

## 4. Форвардные мультипликаторы и консенсус-прогноз

> Раздел носит справочный характер и не влияет на балл экспресс-чеклиста из раздела 1 — это форвардный (консенсусный) взгляд, балансирующий DCF-модель, построенную на экстраполяции исторических 4 лет.

- Forward P/E: **{forward_pe_txt}** [источник: {forward_outlook['forward_pe_source'] or 'N/A'}]
- Ожидаемый рост (консенсус): **{growth_txt}** [источник: {forward_outlook['growth_source'] or 'N/A'}]
- PEG Ratio: **{peg_txt}** {peg_emoji} — {peg_label} [источник: {forward_outlook['peg_source'] or 'N/A'}]

## 5. Катализаторы и риски (качественная оценка)

{catalysts_block}

---
Фундаментальный анализ отвечает на вопрос «что покупать» — точку входа по времени нужно определять в связке с техническим анализом.
"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    md_filename = os.path.join(OUTPUT_DIR, f"{ticker}_fundamental_report_{date_str}.md")
    with open(md_filename, "w") as f:
        f.write(md)
    return md_filename


def build_pdf_report(ticker, retries=5, retry_delay=5, allow_sample=False, catalysts_text=None):
    data = get_company_data(ticker, retries=retries, retry_delay=retry_delay, allow_sample=allow_sample)
    m = compute_metrics(data)
    forward_outlook = compute_forward_outlook(data.get("info", {}), m["price"], m["eps"], m["cagr"])
    catalysts_text = catalysts_text or CATALYSTS_PLACEHOLDER

    name = data["name"]
    price_kind = data["price_kind"]
    quote_time_label = data["quote_time_label"]
    financial_ccy = data.get("financial_currency", "USD")
    trading_ccy = data.get("trading_currency", "USD")
    fx_note = (
        f" (отчётность в {financial_ccy}, конвертирована в {trading_ccy} по курсу {data.get('fx_rate', 1.0):.4f})"
        if financial_ccy != trading_ccy else ""
    )
    price = m["price"]
    beta = m["beta"]
    year_labels = m["year_labels"]
    revenue = m["revenue"]
    operating_income = m["operating_income"]
    net_income = m["net_income"]
    eps = m["eps"]
    curr_assets = m["curr_assets"]
    curr_liab = m["curr_liab"]
    curr_ratios = m["curr_ratios"]
    equity = m["equity"]
    fcf = m["fcf"]
    sins = m["sins"]
    verdict = m["verdict"]
    verdict_color = COLORS[m["verdict_color_key"]]
    reasoning = m["reasoning"]
    wacc = m["wacc"]
    cagr = m["cagr"]
    proj_years = m["proj_years"]
    projected_fcfs = m["projected_fcfs"]
    pv_fcfs = m["pv_fcfs"]
    enterprise_value = m["enterprise_value"]
    net_debt = m["net_debt"]
    debt_lines = _debt_lines(m, trading_ccy)
    cost_of_equity = m["cost_of_equity"]
    cost_of_debt_after_tax = m["cost_of_debt_after_tax"]
    equity_weight = m["equity_weight"]
    debt_weight = m["debt_weight"]
    equity_value = m["equity_value"]
    fair_value_share = m["fair_value_share"]
    val_status = m["val_status"]
    val_color = COLORS[m["val_color_key"]]
    sensitivity_headers = m["sensitivity_headers"]
    sensitivity_rows = m["sensitivity_rows"]

    chart_img_path = generate_fcf_chart(
        year_labels, fcf.values, proj_years, projected_fcfs, ticker
    )

    date_str = datetime.now().strftime("%Y-%m-%d")
    pdf_filename = os.path.join(OUTPUT_DIR, f"{ticker}_fundamental_report_{date_str}.pdf")

    doc = BaseDocTemplate(
        pdf_filename,
        pagesize=PAGE_SIZE,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN + 15,
        bottomMargin=MARGIN,
    )

    content_frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        USABLE_W,
        PAGE_H - doc.topMargin - doc.bottomMargin,
        id="main",
    )

    def on_later_pages(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(COLORS["accent"])
        canvas.setLineWidth(1.2)
        y_rule = PAGE_H - MARGIN + 4
        canvas.line(MARGIN, y_rule, PAGE_W - MARGIN, y_rule)

        canvas.setFont(FONT_BOLD, 8)
        canvas.setFillColor(COLORS["muted"])
        canvas.drawString(
            MARGIN,
            y_rule + 4,
            f"ФУНДАМЕНТАЛЬНЫЙ АНАЛИЗ И ОЦЕНКА СТОИМОСТИ: {ticker.upper()}",
        )
        canvas.drawRightString(PAGE_W - MARGIN, y_rule + 4, f"{name.upper()}")

        y_footer = MARGIN - 24
        canvas.setStrokeColor(COLORS["bg_alt"])
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, y_footer + 12, PAGE_W - MARGIN, y_footer + 12)

        canvas.setFont(FONT_NAME, 8)
        canvas.setFillColor(COLORS["muted"])
        canvas.drawString(
            MARGIN, y_footer, "Подготовлено ИИ-помощником фундаментального анализа"
        )
        canvas.drawRightString(PAGE_W - MARGIN, y_footer, f"Страница {doc.page}")
        canvas.restoreState()

    doc.addPageTemplates(
        [PageTemplate(id="content", frames=content_frame, onPage=on_later_pages)]
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "DocTitle", fontName=FONT_BOLD, fontSize=20, textColor=COLORS["heading"],
        leading=24, spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        "DocSub", fontName=FONT_NAME, fontSize=11, textColor=COLORS["muted"],
        leading=14, spaceAfter=15,
    )
    h1_style = ParagraphStyle(
        "H1", fontName=FONT_BOLD, fontSize=12, textColor=COLORS["heading"],
        leading=15, spaceBefore=12, spaceAfter=6, keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "Body", fontName=FONT_NAME, fontSize=9.5, textColor=COLORS["body"],
        leading=13.5, spaceAfter=6, alignment=TA_JUSTIFY,
    )
    verdict_text_style = ParagraphStyle(
        "VerdictText", fontName=FONT_BOLD, fontSize=12, textColor=verdict_color,
        leading=15, spaceAfter=6,
    )
    callout_text_style = ParagraphStyle(
        "CalloutText", fontName=FONT_NAME, fontSize=9, textColor=COLORS["body"], leading=13,
    )

    story = []

    story.append(
        Paragraph(f"ФУНДАМЕНТАЛЬНЫЙ АНАЛИЗ &amp; ОЦЕНКА DCF: {ticker.upper()}", title_style)
    )
    story.append(
        Paragraph(
            f"Полный отчет по компании: <b>{name}</b> | Цена: <b>{price:.2f} {trading_ccy}</b> "
            f"({price_kind}, Yahoo Finance, {quote_time_label})",
            subtitle_style,
        )
    )
    story.append(SectionDivider(USABLE_W, COLORS["accent"]))
    story.append(Spacer(1, 10))

    # ── SECTION 1: EXECUTIVE VERDICT ────────────────────────────────────
    story.append(Paragraph("1. Экспресс-вердикт и оценка рисков", h1_style))
    story.append(Paragraph("<b>Итоговое решение по алгоритму:</b>", body_style))
    story.append(Paragraph(verdict, verdict_text_style))
    story.append(Paragraph(f"<b>Резюме и обоснование:</b> {reasoning}", body_style))

    if m["critical_sins"]:
        crit_text = (
            "<b>Критические риски (любой из них — основание для ПРОПУСТИТЬ):</b><br/>"
            + "<br/>".join(f"• {escape_xml(s.message)}" for s in m["critical_sins"])
        )
        story.append(CalloutBox(crit_text, USABLE_W, COLORS, callout_text_style, COLORS["danger"]))
        story.append(Spacer(1, 6))
    if m["minor_sins"]:
        minor_text = (
            f"<b>Второстепенные риски (балл {m['minor_score']:.1f} из {m['max_minor_score']:.1f}):</b><br/>"
            + "<br/>".join(f"• [{s.weight:.1f}] {escape_xml(s.message)}" for s in m["minor_sins"])
        )
        story.append(CalloutBox(minor_text, USABLE_W, COLORS, callout_text_style, COLORS["warning"]))
    if not sins:
        story.append(
            CalloutBox(
                "<b>Финансовые риски:</b> Грехов не обнаружено. Финансовые показатели компании находятся в безупречной форме.",
                USABLE_W, COLORS, callout_text_style, COLORS["success"],
            )
        )

    story.append(Spacer(1, 12))

    # ── SECTION 2: FUNDAMENTAL TRENDS ───────────────────────────────────
    story.append(Paragraph("2. Экспресс-анализ финансовых результатов и баланса", h1_style))
    story.append(
        Paragraph(
            "Ниже представлена сводная таблица фундаментальных показателей компании за последние 4 отчетных года. "
            f"Основной упор сделан на динамику изменения капитала, ликвидности и денежных потоков.{fx_note}",
            body_style,
        )
    )

    last4 = range(len(year_labels) - 4, len(year_labels))
    fund_headers = [f"Показатель (в млн. {trading_ccy})"] + [year_labels[i] for i in last4]
    fund_rows = [
        ["Выручка (Revenue)"] + [f"{revenue.iloc[i] / 1e6:,.1f}" for i in last4],
        ["Операционная прибыль (Operating Income)"] + [f"{operating_income.iloc[i] / 1e6:,.1f}" for i in last4],
        ["Чистая прибыль (Net Income)"] + [f"{net_income.iloc[i] / 1e6:,.1f}" for i in last4],
        ["Разводненная прибыль на акцию (EPS, USD)"] + [f"{eps.iloc[i]:.2f}" for i in last4],
        ["Оборотные активы (Current Assets)"] + [f"{curr_assets.iloc[i] / 1e6:,.1f}" for i in last4],
        ["Краткосрочные обязательства (Current Liab)"] + [f"{curr_liab.iloc[i] / 1e6:,.1f}" for i in last4],
        ["Текущая ликвидность (Current Ratio)"] + [f"{curr_ratios.iloc[i]:.2f}" for i in last4],
        ["Акционерный капитал (Shareholders Equity)"] + [f"{equity.iloc[i] / 1e6:,.1f}" for i in last4],
        ["Чистый Свободный кэш (Free Cash Flow)"] + [f"{fcf.iloc[i] / 1e6:,.1f}" for i in last4],
    ]

    story.append(
        create_reportlab_table(fund_headers, fund_rows, styles, COLORS, col_widths=[190, 70, 70, 70, 70])
    )
    story.append(Spacer(1, 10))

    story.append(Image(chart_img_path, width=USABLE_W, height=USABLE_W * 0.4))
    story.append(Spacer(1, 12))

    # ── SECTION 3: DCF DETAILED MODEL ───────────────────────────────────
    story.append(Paragraph("3. Модель дисконтирования денежных потоков (DCF)", h1_style))
    story.append(
        Paragraph(
            "Расчет справедливой стоимости на основе темпов роста FCF и средневзвешенной стоимости капитала (WACC):",
            body_style,
        )
    )

    debt_html = "<br/>".join(f"• <b>{label}:</b> {value}" for label, value in debt_lines)
    dcf_info_text = (
        f"• <b>Стоимость собственного капитала (CAPM):</b> Ke = Rf + β×ERP = 4% + {beta:.2f}×5% = {cost_of_equity * 100:.2f}%<br/>"
        f"• <b>Стоимость долга после налога:</b> Kd×(1-T) = 4.5%×(1-21%) = {cost_of_debt_after_tax * 100:.2f}% "
        f"(Kd=4.5%, T=21% — фиксированные допущения методики, не эффективная налоговая ставка компании)<br/>"
        f"• <b>Веса структуры капитала:</b> E/(D+E) = {equity_weight * 100:.1f}%, D/(D+E) = {debt_weight * 100:.1f}% "
        f"(по рыночной капитализации, не по балансовому капиталу — у компаний с отрицательным book equity вес по балансу был бы недействителен)<br/>"
        f"• <b>Итоговый WACC:</b> {equity_weight * 100:.1f}%×{cost_of_equity * 100:.2f}% + {debt_weight * 100:.1f}%×{cost_of_debt_after_tax * 100:.2f}% = <b>{wacc * 100:.2f}%</b><br/>"
        f"• <b>Расчетный CAGR роста потока:</b> {cagr * 100:.2f}% (среднеисторический темп роста, ограничен консервативной границей)<br/>"
        f"• <b>Терминальный темп роста:</b> 2.5% (пожизненный темп роста компании в постпрогнозный период)<br/>"
        f"{debt_html}<br/>"
        f"• <b>Справедливая оценка акционерного капитала:</b> {equity_value / 1e9:,.2f} млрд. {trading_ccy} (Enterprise Value = {enterprise_value / 1e9:,.2f} млрд. {trading_ccy})<br/>"
    )
    story.append(CalloutBox(dcf_info_text, USABLE_W, COLORS, callout_text_style, COLORS["accent"]))
    story.append(CalloutBox(LEASE_ASSUMPTION_NOTE, USABLE_W, COLORS, callout_text_style, COLORS["muted"]))
    story.append(Spacer(1, 8))

    val_banner_text = (
        f"<b>СПРАВЕДЛИВАЯ СТОИМОСТЬ АКЦИИ: {fair_value_share:.2f} {trading_ccy}</b><br/>"
        f"Последняя доступная рыночная котировка: {price:.2f} {trading_ccy} ({price_kind}, {quote_time_label}) "
        f"| Статус: <font color='{val_color.hexval()}'><b>{val_status}</b></font>"
    )
    story.append(
        CalloutBox(
            val_banner_text, USABLE_W, COLORS,
            ParagraphStyle("ValB", parent=callout_text_style, fontSize=10, leading=14),
            val_color,
        )
    )
    story.append(Spacer(1, 10))

    proj_headers = ["Прогнозный показатель", "Год 1", "Год 2", "Год 3", "Год 4", "Год 5"]
    proj_rows = [
        ["Прогнозный FCF (млн. USD)"] + [f"{v / 1e6:,.1f}" for v in projected_fcfs],
        ["Дисконтированный FCF (PV, млн.)"] + [f"{v / 1e6:,.1f}" for v in pv_fcfs],
    ]
    story.append(
        create_reportlab_table(proj_headers, proj_rows, styles, COLORS, col_widths=[170, 60, 60, 60, 60, 60])
    )
    story.append(Spacer(1, 12))

    story.append(
        Paragraph(
            "<b>Матрица чувствительности цены акции (WACC vs Рост g):</b>",
            ParagraphStyle("SensT", fontName=FONT_BOLD, fontSize=9.5, textColor=COLORS["heading"], spaceAfter=4),
        )
    )
    story.append(
        Paragraph(
            "Таблица показывает, как меняется внутренняя стоимость одной акции при изменении ставки дисконтирования и темпов роста FCF. Позволяет оценить диапазон цен при различных сценариях развития рынка. "
            "<b>Важно:</b> g в этой матрице — темп роста явного 5-летнего прогноза FCF, а не терминальный рост. "
            "Терминальный рост зафиксирован отдельно на 2.5% и используется только в формуле Гордона для стоимости после 5-го года — "
            "условие WACC &gt; g в этой матрице не требуется, оно требуется только для WACC &gt; терминальный рост (2.5%), что и проверяется отдельно.",
            body_style,
        )
    )
    story.append(create_reportlab_table(sensitivity_headers, sensitivity_rows, styles, COLORS))
    story.append(Spacer(1, 12))

    # ── SECTION 4: FORWARD OUTLOOK ──────────────────────────────────────
    story.append(Paragraph("4. Форвардные мультипликаторы и консенсус-прогноз", h1_style))
    story.append(
        Paragraph(
            "Раздел носит исключительно информационный характер и не влияет на балл экспресс-чеклиста "
            "из раздела 1 — это форвардный (консенсусный) взгляд, балансирующий DCF-модель, построенную "
            "на экстраполяции исторических 4 лет.",
            body_style,
        )
    )
    peg_color_key, peg_label = _peg_assessment(forward_outlook["peg_ratio"])
    outlook_text = (
        f"• <b>Forward P/E:</b> {_fmt_or_na(forward_outlook['forward_pe'])} "
        f"[источник: {escape_xml(forward_outlook['forward_pe_source'] or 'N/A')}]<br/>"
        f"• <b>Ожидаемый рост (консенсус):</b> {_fmt_or_na(forward_outlook['growth_pct'], '{:.1f}%')} "
        f"[источник: {escape_xml(forward_outlook['growth_source'] or 'N/A')}]<br/>"
        f"• <b>PEG Ratio:</b> {_fmt_or_na(forward_outlook['peg_ratio'])} — "
        f"<font color='{COLORS[peg_color_key].hexval()}'><b>{escape_xml(peg_label)}</b></font> "
        f"[источник: {escape_xml(forward_outlook['peg_source'] or 'N/A')}]<br/>"
    )
    story.append(CalloutBox(outlook_text, USABLE_W, COLORS, callout_text_style, COLORS[peg_color_key]))
    story.append(Spacer(1, 12))

    # ── SECTION 5: QUALITATIVE CATALYSTS ────────────────────────────────
    story.append(Paragraph("5. Катализаторы и риски (качественная оценка)", h1_style))
    catalysts_html = "<br/>".join(escape_xml(line) for line in catalysts_text.splitlines())
    story.append(CalloutBox(catalysts_html, USABLE_W, COLORS, callout_text_style, COLORS["muted"]))
    story.append(Spacer(1, 12))

    warning_text = (
        "<b>Важное правило методики экспресс-анализа:</b><br/>"
        "Фундаментальный анализ дает нам ответ на вопрос <b>что именно</b> покупать. Однако для определения "
        "наилучшего момента и цены входа, фундаментальный анализ <b>обязательно должен использоваться в связке с "
        "техническим анализом</b>. Не пытайтесь применять их отдельно! Справедливая стоимость по модели DCF часто "
        "достигается только при возникновении катализаторов рыночного спроса или корпоративных скандалов, временно занижающих цену."
    )
    story.append(CalloutBox(warning_text, USABLE_W, COLORS, callout_text_style, COLORS["warning"]))

    doc.build(story)
    print(f"Success! Comprehensive report saved to: {pdf_filename}")

    md_filename = build_markdown_report(ticker, data, m, forward_outlook, catalysts_text)
    print(f"Success! Markdown report saved to: {md_filename}")

    return pdf_filename, md_filename


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Comprehensive Fundamental Express Analyzer & DCF Model"
    )
    parser.add_argument(
        "ticker", type=str, nargs="?", default="AAPL",
        help="Stock ticker symbol (e.g. AAPL, MSFT, TSLA)",
    )
    parser.add_argument(
        "--retries", type=int, default=5,
        help="How many times to retry Yahoo Finance before giving up (default 5)",
    )
    parser.add_argument(
        "--retry-delay", type=int, default=5,
        help="Seconds to wait between retries (default 5)",
    )
    parser.add_argument(
        "--allow-sample", action="store_true",
        help="Fall back to labeled SAMPLE data if real data can't be fetched (demo only, off by default)",
    )
    parser.add_argument(
        "--catalysts", type=str, default=None,
        help="Free-text note on catalysts/risks to embed in the report (e.g. product launch, regulatory event).",
    )
    parser.add_argument(
        "--catalysts-file", type=str, default=None,
        help="Path to a text file with the catalysts note (alternative to --catalysts).",
    )
    args = parser.parse_args()

    catalysts_text = resolve_catalysts_text(args.catalysts, args.catalysts_file)

    try:
        build_pdf_report(
            args.ticker, retries=args.retries, retry_delay=args.retry_delay,
            allow_sample=args.allow_sample, catalysts_text=catalysts_text,
        )
    except DataUnavailableError as e:
        print(f"FAILED: {e}")
        raise SystemExit(1)
