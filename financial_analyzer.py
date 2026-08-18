import argparse
import os
import time

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

        price = info.get("currentPrice") or info.get("previousClose")
        shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
        if not price or not shares:
            return None

        beta = info.get("beta") or 1.1
        name = info.get("longName") or info.get("shortName") or ticker

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

    curr_assets = find_row(df_bal, ["total current assets", "current assets"])
    curr_liab = find_row(df_bal, ["total current liabilities", "current liabilities"])
    total_assets = find_row(df_bal, ["total assets"])
    goodwill = find_row(df_bal, ["goodwill"])
    equity = find_row(df_bal, ["stockholders equity", "total stockholders equity"])
    debt = find_row(df_bal, ["total debt", "long term debt"])
    cash = find_row(df_bal, ["cash and cash equivalents", "cash cash equivalents"])

    fcf = find_row(df_cf, ["free cash flow", "fcf"])

    curr_ratios = curr_assets / curr_liab
    net_margin = net_income / revenue * 100

    # ── "Sins" checklist (express algorithm from the lecture) ──────────
    sins = []

    latest_cr = curr_ratios.iloc[-1]
    if latest_cr < 1.0:
        sins.append(
            f"Критическая ликвидность: коэффициент текущей ликвидности (Current Ratio) ниже 1.0 ({latest_cr:.2f})."
        )
    elif latest_cr < 1.5:
        sins.append(
            f"Сниженная ликвидность: Current Ratio {latest_cr:.2f} (желательно выше 1.5-2.0)."
        )
    if len(curr_ratios) >= 2 and curr_ratios.iloc[-1] < curr_ratios.iloc[-2]:
        sins.append(
            f"Снижающийся тренд ликвидности: Current Ratio с {curr_ratios.iloc[-2]:.2f} до {curr_ratios.iloc[-1]:.2f}."
        )

    latest_equity = equity.iloc[-1]
    if latest_equity <= 0:
        sins.append("Отрицательный акционерный капитал: обязательств больше, чем реальных активов.")
    elif len(equity) >= 2 and equity.iloc[-1] < equity.iloc[-2]:
        sins.append("Тренд падения капитала: Shareholder Equity снизился за последний год.")

    latest_fcf = fcf.iloc[-1]
    if latest_fcf <= 0:
        sins.append("Сжигание денежных средств: отрицательный Free Cash Flow.")
    elif len(fcf) >= 2 and fcf.iloc[-1] < fcf.iloc[-2]:
        sins.append("Падение денежного потока: снижение FCF за последний год.")

    if len(revenue) >= 2 and revenue.iloc[-1] < revenue.iloc[-2]:
        sins.append("Снижение выручки за последний год.")
    if len(net_income) >= 2 and net_income.iloc[-1] < net_income.iloc[-2]:
        sins.append("Падение чистой прибыли за последний год.")
    if len(net_margin) >= 2 and net_margin.iloc[-1] < net_margin.iloc[-2]:
        sins.append(
            f"Падение рентабельности: чистая маржа с {net_margin.iloc[-2]:.1f}% до {net_margin.iloc[-1]:.1f}%."
        )

    if len(sins) == 0:
        verdict = "🟢 КУПИТЬ / СИЛЬНЫЙ КАНДИДАТ"
        verdict_color_key = "success"
        reasoning = "Компания демонстрирует эталонную финансовую устойчивость, растущую выручку, отличную маржинальность и растущий свободный денежный поток. Риски минимальны."
    elif len(sins) <= 2:
        verdict = "🟡 НАБЛЮДАТЬ / ОГРАНИЧЕННАЯ ДОЛЯ"
        verdict_color_key = "warning"
        reasoning = "Отличный сильный бизнес, однако в финансовых трендах или балансе присутствуют незначительные погрешности. Рекомендуется покупка только ограниченной долей."
    else:
        verdict = "🔴 ПРОПУСТИТЬ / ВЫСОКИЙ РИСК"
        verdict_color_key = "danger"
        reasoning = f"Обнаружено {len(sins)} финансовых нарушений (грехов). Слабая ликвидность, падающие потоки капитала или отрицательный свободный кэш делают эту инвестицию крайне рискованной на текущем этапе."

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
    net_debt = latest_debt - latest_cash
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
        "verdict": verdict,
        "verdict_color_key": verdict_color_key,
        "reasoning": reasoning,
        "beta": beta,
        "wacc": wacc,
        "cagr": cagr,
        "proj_years": proj_years,
        "projected_fcfs": projected_fcfs,
        "pv_fcfs": pv_fcfs,
        "enterprise_value": enterprise_value,
        "net_debt": net_debt,
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


# ── MAIN PDF COMPILER ───────────────────────────────────────────────────
def build_pdf_report(ticker, retries=5, allow_sample=False):
    data = get_company_data(ticker, retries=retries, allow_sample=allow_sample)
    m = compute_metrics(data)

    name = data["name"]
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
    equity_value = m["equity_value"]
    fair_value_share = m["fair_value_share"]
    val_status = m["val_status"]
    val_color = COLORS[m["val_color_key"]]
    sensitivity_headers = m["sensitivity_headers"]
    sensitivity_rows = m["sensitivity_rows"]

    chart_img_path = generate_fcf_chart(
        year_labels, fcf.values, proj_years, projected_fcfs, ticker
    )

    pdf_filename = os.path.join(OUTPUT_DIR, f"{ticker}_fundamental_report.pdf")

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
            f"Полный отчет по компании: <b>{name}</b> | Текущая цена: <b>{price:.2f} USD</b>",
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

    if sins:
        sins_text = (
            "<b>Выявленные финансовые риски («грехи» компании):</b><br/>"
            + "<br/>".join([f"• {escape_xml(s)}" for s in sins])
        )
        story.append(CalloutBox(sins_text, USABLE_W, COLORS, callout_text_style, COLORS["danger"]))
    else:
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
            "Ниже представлена сводная таблица фундаментальных показателей компании за последние 4 отчетных года. Основной упор сделан на динамику изменения капитала, ликвидности и денежных потоков.",
            body_style,
        )
    )

    fund_headers = ["Показатель (в млн. USD)", year_labels[0], year_labels[1], year_labels[2], year_labels[3]]
    fund_rows = [
        ["Выручка (Revenue)"] + [f"{revenue.iloc[i] / 1e6:,.1f}" for i in range(4)],
        ["Операционная прибыль (Operating Income)"] + [f"{operating_income.iloc[i] / 1e6:,.1f}" for i in range(4)],
        ["Чистая прибыль (Net Income)"] + [f"{net_income.iloc[i] / 1e6:,.1f}" for i in range(4)],
        ["Разводненная прибыль на акцию (EPS, USD)"] + [f"{eps.iloc[i]:.2f}" for i in range(4)],
        ["Оборотные активы (Current Assets)"] + [f"{curr_assets.iloc[i] / 1e6:,.1f}" for i in range(4)],
        ["Краткосрочные обязательства (Current Liab)"] + [f"{curr_liab.iloc[i] / 1e6:,.1f}" for i in range(4)],
        ["Текущая ликвидность (Current Ratio)"] + [f"{curr_ratios.iloc[i]:.2f}" for i in range(4)],
        ["Акционерный капитал (Shareholders Equity)"] + [f"{equity.iloc[i] / 1e6:,.1f}" for i in range(4)],
        ["Чистый Свободный кэш (Free Cash Flow)"] + [f"{fcf.iloc[i] / 1e6:,.1f}" for i in range(4)],
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

    dcf_info_text = (
        f"• <b>Базовая ставка дисконтирования (WACC):</b> {wacc * 100:.2f}% (на основе беты β = {beta:.2f}, Rf = 4%, ERP = 5%)<br/>"
        f"• <b>Расчетный CAGR роста потока:</b> {cagr * 100:.2f}% (среднеисторический темп роста, ограничен консервативной границей)<br/>"
        f"• <b>Терминальный темп роста:</b> 2.5% (пожизненный темп роста компании в постпрогнозный период)<br/>"
        f"• <b>Справедливая оценка акционерного капитала:</b> {equity_value / 1e9:,.2f} млрд. USD (Enterprise Value = {enterprise_value / 1e9:,.2f} млрд. USD, Чистый долг = {net_debt / 1e9:,.2f} млрд. USD)<br/>"
    )
    story.append(CalloutBox(dcf_info_text, USABLE_W, COLORS, callout_text_style, COLORS["accent"]))
    story.append(Spacer(1, 8))

    val_banner_text = (
        f"<b>СПРАВЕДЛИВАЯ СТОИМОСТЬ АКЦИИ: {fair_value_share:.2f} USD</b><br/>"
        f"Текущая рыночная цена: {price:.2f} USD | Статус: <font color='{val_color.hexval()}'><b>{val_status}</b></font>"
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
            "Таблица показывает, как меняется внутренняя стоимость одной акции при изменении ставки дисконтирования и темпов роста FCF. Позволяет оценить диапазон цен при различных сценариях развития рынка.",
            body_style,
        )
    )
    story.append(create_reportlab_table(sensitivity_headers, sensitivity_rows, styles, COLORS))
    story.append(Spacer(1, 12))

    warning_text = (
        "<b>Важное инвесторское правило из курса ИФИ:</b><br/>"
        "Фундаментальный анализ дает нам ответ на вопрос <b>что именно</b> покупать. Однако для определения "
        "наилучшего момента и цены входа, фундаментальный анализ <b>обязательно должен использоваться в связке с "
        "техническим анализом</b>. Не пытайтесь применять их отдельно! Справедливая стоимость по модели DCF часто "
        "достигается только при возникновении катализаторов рыночного спроса или корпоративных скандалов, временно занижающих цену."
    )
    story.append(CalloutBox(warning_text, USABLE_W, COLORS, callout_text_style, COLORS["warning"]))

    doc.build(story)
    print(f"Success! Comprehensive report saved to: {pdf_filename}")
    return pdf_filename


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
        "--allow-sample", action="store_true",
        help="Fall back to labeled SAMPLE data if real data can't be fetched (demo only, off by default)",
    )
    args = parser.parse_args()

    try:
        build_pdf_report(args.ticker, retries=args.retries, allow_sample=args.allow_sample)
    except DataUnavailableError as e:
        print(f"FAILED: {e}")
        raise SystemExit(1)
