import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime

# Resolve workspace root relative to this script file
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRATCH_DIR = os.path.join(SCRIPT_DIR, "scratch")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
os.makedirs(SCRATCH_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Package-under-migration lives in src/ (docs/spec/refactor-architecture-spec.md)
# and isn't installed - add it to sys.path so `python financial_analyzer.py`
# keeps working unchanged from any working directory.
sys.path.insert(0, os.path.join(SCRIPT_DIR, "src"))

import pandas as pd

from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageTemplate,
    Paragraph,
    Spacer,
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
    "dilution": 1.0,
    "cr_below_1_bypassed": 1.0,
    "cr_declining": 0.5,
    "gross_margin_declining": 0.5,
    "operating_margin_declining": 0.5,
    "net_income_declining": 0.3,
    "net_margin_declining": 0.3,
}
# Buyback bonus is a reduction, not a badness ceiling - deliberately excluded
# from MAX_MINOR_SCORE (which sums only the positive weights above).
BUYBACK_BONUS_WEIGHT = -0.5
MAX_MINOR_SCORE = sum(MINOR_SIN_WEIGHTS.values())

# Ordinary v3 (Step 4, docs/spec/step4-ordinary-v3-implementation-spec.md
# Section 2.1/2.2.1) - technical_negative_equity/technical_lt_insolvency are
# the minor sins substituted in when the matching CRITICAL sin is smart-
# bypassed for a buyback-distorted balance sheet. Deliberately kept OUT of
# MINOR_SIN_WEIGHTS/MAX_MINOR_SCORE (same reasoning as BUYBACK_BONUS_WEIGHT
# above): each is mutually exclusive with its own critical sin AND with the
# corresponding "*_declining" minor sin (equity_declining only fires when
# equity > 0; these only fire when equity <= 0 / lt-insolvent), so folding
# them into the theoretical worst-case ceiling would overstate a combination
# that can never actually occur - and it would silently break the existing
# test asserting MAX_MINOR_SCORE == 8.1.
TECHNICAL_NEGATIVE_EQUITY_WEIGHT = 1.0
TECHNICAL_LT_INSOLVENCY_WEIGHT = 1.0

# ── VISUAL THEME (colors, fonts, page geometry) ─────────────────────────
# Moved to src/fundamental_express/reporting/theme.py (docs/spec/refactor-tasks.md T02).
from fundamental_express.reporting.theme import (  # noqa: E402
    COLORS,
    FONT_NAME,
    FONT_BOLD,
    PAGE_SIZE,
    MARGIN,
    PAGE_W,
    PAGE_H,
    USABLE_W,
    escape_xml,
    _fmt_or_na,
)


# ── FINANCIAL STATEMENT PARSING (row locator, year alignment) ──────────
# Moved to src/fundamental_express/data/parsing.py (docs/spec/refactor-tasks.md T06).
from fundamental_express.data.parsing import find_row, _align_statement_years  # noqa: E402


# ── ERRORS ───────────────────────────────────────────────────────────────
# Moved to src/fundamental_express/data/errors.py (docs/spec/refactor-tasks.md T07).
from fundamental_express.data.errors import DataUnavailableError, UnsupportedSectorError  # noqa: E402


# Moved to src/fundamental_express/domain/routing.py (docs/spec/refactor-tasks.md T08).
from fundamental_express.domain.routing import check_sector_suitability  # noqa: E402


# ── DATA LAYER (Yahoo Finance client, FX bridge, SAMPLE fallback) ───────
# Moved to src/fundamental_express/data/yahoo.py and data/sample.py
# (docs/spec/refactor-tasks.md T09).
from fundamental_express.data.yahoo import (  # noqa: E402
    YFINANCE_AVAILABLE,
    _fx_rate,
    _fetch_once,
    get_company_data,
)
from fundamental_express.data.sample import _sample_data  # noqa: E402


# ── PDF FLOWABLES (section divider, callout box, sector warning banner) ─
# Moved to src/fundamental_express/reporting/flowables.py (docs/spec/refactor-tasks.md T03).
from fundamental_express.reporting.flowables import (  # noqa: E402
    SectionDivider,
    CalloutBox,
    SectorWarningBanner,
)


# ── SHARED PDF TABLE BUILDER ─────────────────────────────────────────────
# Moved to src/fundamental_express/reporting/tables.py (docs/spec/refactor-tasks.md T04).
from fundamental_express.reporting.tables import create_reportlab_table  # noqa: E402


# ── CHART GENERATORS (FCF/NII/FFO) ──────────────────────────────────────
# Moved to src/fundamental_express/reporting/charts.py (docs/spec/refactor-tasks.md T05).
from fundamental_express.reporting.charts import (  # noqa: E402
    generate_fcf_chart,
    generate_nii_chart,
    generate_ffo_chart,
)


# ── CORE ANALYSIS: EXPRESS "SINS" CHECKLIST + DCF ───────────────────────
def compute_metrics(data, required_return=None):
    """Run the express sins-checklist and the CAPM/DCF valuation on `data`.

    This is the single source of truth for both the per-company PDF report
    and the multi-company comparative tool - the two must never compute
    this differently.

    `required_return`, if given, overrides the CAPM-derived cost of equity
    (Ke) with the investor's own required rate of return - see
    docs/spec/step1-ordinary-router-implementation-spec.md Section 2.4.
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

    # Diluted share count (income statement, historical per-year) - used for
    # the Dilution/Buyback sins. This is a share COUNT, not a monetary
    # figure, so it's never FX-converted below (unlike current_debt).
    diluted_shares = find_row(
        df_fin, ["diluted average shares", "basic average shares"], default_val=float("nan")
    )
    # Short-term interest-bearing debt (the portion due within a year) - used
    # only by the Current Ratio smart-bypass (Section 2.3): if a company's
    # cash comfortably covers this, a CR < 1.0 driven by non-debt current
    # liabilities is a much smaller red flag than an inability to service
    # near-term debt.
    current_debt = find_row(
        df_bal, ["current debt", "short term debt", "short long term debt"], default_val=float("nan")
    )
    # Ordinary v3 (Step 4, spec Section 2.2 Scenario 2 / 2.3): Interest
    # Expense for the Interest Coverage Ratio proxy (replaces an external
    # credit rating - yfinance.info has no such field for ~all tickers,
    # live-verified against MCD/AAPL), and dividend history for the DDM
    # switch. Missing rows default to NaN, never 0.0 - a genuinely
    # interest-free company is handled explicitly below (auto-pass on the
    # ICR check), never conflated with "row not found".
    interest_expense = find_row(
        df_fin, ["interest expense", "interest expense non operating"], default_val=float("nan")
    )
    cash_dividends_paid = find_row(
        df_cf, ["cash dividends paid", "common stock dividend paid", "payment of dividends"],
        default_val=float("nan"),
    )

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
        current_debt = current_debt * fx_rate
        interest_expense = interest_expense * fx_rate
        cash_dividends_paid = cash_dividends_paid * fx_rate

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

    # Net debt - moved ahead of the sins checklist (Ordinary v3, Step 4):
    # the Current Ratio smart-bypass Scenario 2 needs it for the Net Debt /
    # Operating Income leverage check. Formula/values are unchanged from
    # the original DCF-section placement, just computed earlier so both
    # the checklist and the DCF valuation below can reuse the same numbers.
    latest_debt = debt.iloc[-1]
    if pd.isna(latest_debt) or latest_debt < 0:
        latest_debt = 0.0
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

    # ── "Sins" checklist (express algorithm from the lecture, two-tier) ──
    sins = []

    latest_fcf = fcf.iloc[-1]
    latest_cr = curr_ratios.iloc[-1]
    # Ordinary v3 (Step 4, spec Section 2.1/2.2.1): a stable, mature company
    # can show negative book equity or "long-term insolvency" purely from
    # decades of buybacks (Treasury Stock), not operating distress. Both
    # the equity_negative and lt_insolvency critical sins below check this
    # SAME three-condition proof before being smart-bypassed to a minor sin
    # instead: positive Operating Income and FCF in every available year
    # (up to 4), plus an actively shrinking share count (proof of buyback,
    # not just an assertion).
    buyback_distortion_bypass = (
        len(operating_income) > 0 and bool((operating_income > 0).all())
        and len(fcf) > 0 and bool((fcf > 0).all())
        and not diluted_shares.isna().any()
        and len(diluted_shares) >= 2
        and diluted_shares.iloc[-1] < diluted_shares.iloc[-2]
    )
    # Smart bypass: a Current Ratio below 1.0 driven by, say, deferred revenue
    # or accounts payable isn't the same red flag as an inability to service
    # actual near-term debt. Two independent scenarios grant leniency
    # (Ordinary v3, Step 4 Section 2.2 adds Scenario 2 alongside the
    # original Scenario 1) - either is sufficient on its own:
    #   Scenario 1: FCF-positive and cash alone covers short-term debt.
    #     Never granted on missing current_debt data - leniency requires
    #     proof, not the absence of a red flag.
    #   Scenario 2: FCF-positive, overall leverage is safe (Net Debt /
    #     Operating Income < 4.0 - the 3.0 spec default is raised to 4.0
    #     since Operating Income/EBIT proxies EBITDA and over-penalizes
    #     capital-intensive real-estate-heavy businesses), and interest
    #     coverage is strong (Operating Income / Interest Expense > 4.0 -
    #     an objective proxy for investment-grade debt, since yfinance.info
    #     carries no credit-rating field for virtually any ticker). A
    #     company with no interest-bearing debt at all (Interest Expense
    #     missing/0/NaN) auto-passes the coverage leg - silence there is
    #     never treated as a red flag. Requires a genuine net debt balance
    #     (net_debt > 0): a net-CASH company isn't what this leverage-grade
    #     scenario is for, and it belongs to Scenario 1's territory instead
    #     if it wants credit for having more cash than short-term debt.
    cr_bypass_scenario1 = (
        latest_cr < 1.0
        and latest_fcf > 0
        and not pd.isna(current_debt.iloc[-1])
        and not pd.isna(cash.iloc[-1])
        and cash.iloc[-1] > current_debt.iloc[-1]
    )
    latest_op_inc = operating_income.iloc[-1]
    latest_interest_expense = interest_expense.iloc[-1] if len(interest_expense) else float("nan")
    icr_ok = (
        pd.isna(latest_interest_expense)
        or latest_interest_expense == 0
        or (latest_op_inc / latest_interest_expense) > 4.0
    )
    cr_bypass_scenario2 = (
        latest_cr < 1.0
        and latest_fcf > 0
        and latest_op_inc > 0
        and not pd.isna(net_debt)
        and net_debt > 0
        and (net_debt / latest_op_inc) < 4.0
        and icr_ok
    )
    cr_bypass_eligible = cr_bypass_scenario1 or cr_bypass_scenario2
    if latest_cr < 1.0 and not cr_bypass_eligible:
        sins.append(Sin(
            "cr_below_1", "critical", 0.0,
            f"Критическая ликвидность: коэффициент текущей ликвидности (Current Ratio) ниже 1.0 ({latest_cr:.2f}).",
        ))
    elif latest_cr < 1.0 and cr_bypass_eligible:
        reasons = []
        if cr_bypass_scenario1:
            reasons.append(
                f"FCF положительный ({latest_fcf / 1e6:,.0f} млн) и денежные средства "
                f"({cash.iloc[-1] / 1e6:,.0f} млн) превышают краткосрочный долг "
                f"({current_debt.iloc[-1] / 1e6:,.0f} млн)"
            )
        if cr_bypass_scenario2:
            icr_txt = (
                "∞ (процентного долга нет)"
                if pd.isna(latest_interest_expense) or latest_interest_expense == 0
                else f"{latest_op_inc / latest_interest_expense:.2f}"
            )
            reasons.append(
                f"безопасный уровень долговой нагрузки (Net Debt / Operating Income = "
                f"{net_debt / latest_op_inc:.2f}, < 4.0) при сильном покрытии процентов "
                f"(Interest Coverage Ratio = {icr_txt}, > 4.0)"
            )
        sins.append(Sin(
            "cr_below_1_bypassed", "minor", MINOR_SIN_WEIGHTS["cr_below_1_bypassed"],
            f"Ликвидность ниже 1.0 ({latest_cr:.2f}), но не критична: " + "; ".join(reasons) + ".",
        ))
    # A CR decline is only flagged if the company also isn't comfortably
    # liquid (CR >= 2.0) after the decline - dropping from, say, 4.0 to 3.0
    # isn't a red flag on its own. Requiring latest_cr >= 1.0 here keeps this
    # mutually exclusive with the two branches above - a CR crash below 1.0
    # is already captured (critical or bypassed) and must not also
    # double-count as a minor "declining trend" sin on the same fact.
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
        if latest_lt_assets < latest_lt_liab and buyback_distortion_bypass:
            # Ordinary v3 (Step 4, Section 2.2.1): same buyback-distortion
            # story as equity_negative below - book long-term assets fall
            # under liabilities purely from accumulated Treasury Stock, not
            # from operating distress (proven by the same 3 conditions).
            sins.append(Sin(
                "technical_lt_insolvency", "minor", TECHNICAL_LT_INSOLVENCY_WEIGHT,
                "Техническая долгосрочная неплатежеспособность в результате активного выкупа акций "
                "(Buyback) при сильной операционной рентабельности.",
            ))
        elif latest_lt_assets < latest_lt_liab:
            sins.append(Sin(
                "lt_insolvency", "critical", 0.0,
                f"Долгосрочная неплатёжеспособность: скорректированные (за вычетом Goodwill) "
                f"долгосрочные активы ({latest_lt_assets / 1e6:,.0f} млн) меньше долгосрочных "
                f"обязательств ({latest_lt_liab / 1e6:,.0f} млн).",
            ))

    latest_equity = equity.iloc[-1]
    if latest_equity <= 0 and buyback_distortion_bypass:
        # Ordinary v3 (Step 4, Section 2.1): negative book equity purely
        # from decades of buybacks (Treasury Stock), not operating losses -
        # proven by positive Operating Income/FCF every available year plus
        # an actively shrinking share count (buyback_distortion_bypass).
        sins.append(Sin(
            "technical_negative_equity", "minor", TECHNICAL_NEGATIVE_EQUITY_WEIGHT,
            "Технический отрицательный капитал в результате активного выкупа акций (Buyback) при "
            "стабильно сильных операционных и денежных результатах.",
        ))
    elif latest_equity <= 0:
        sins.append(Sin(
            "equity_negative", "critical", 0.0,
            "Отрицательный акционерный капитал: обязательств больше, чем реальных активов.",
        ))
    elif len(equity) >= 2 and equity.iloc[-1] < equity.iloc[-2]:
        sins.append(Sin(
            "equity_declining", "minor", MINOR_SIN_WEIGHTS["equity_declining"],
            "Тренд падения капитала: Shareholder Equity снизился за последний год.",
        ))

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

    # Dilution / buyback bonus: share-count changes economically equivalent
    # to a per-share earnings cut (dilution) or a shareholder-friendly boost
    # (buyback), mutually exclusive since a >1.5% YoY move can only go one
    # direction. Skipped silently if diluted_shares wasn't found for this
    # ticker's statements (default_val=NaN) - never guessed from a partial row.
    if (
        not diluted_shares.isna().any()
        and len(diluted_shares) >= 2
        and diluted_shares.iloc[-2] != 0
    ):
        shares_ratio = diluted_shares.iloc[-1] / diluted_shares.iloc[-2]
        if shares_ratio > 1.015:
            sins.append(Sin(
                "dilution", "minor", MINOR_SIN_WEIGHTS["dilution"],
                f"Размытие долей: средневзвешенное число акций выросло с {diluted_shares.iloc[-2]:,.0f} "
                f"до {diluted_shares.iloc[-1]:,.0f} ({(shares_ratio - 1) * 100:.1f}%).",
            ))
        elif shares_ratio < (1 / 1.015):
            sins.append(Sin(
                "buyback_bonus", "minor", BUYBACK_BONUS_WEIGHT,
                f"Бонус за байбэк: число акций сократилось с {diluted_shares.iloc[-2]:,.0f} "
                f"до {diluted_shares.iloc[-1]:,.0f} ({(1 - shares_ratio) * 100:.1f}%).",
            ))

    critical_sins = [s for s in sins if s.tier == "critical"]
    minor_sins = [s for s in sins if s.tier == "minor"]
    minor_score = max(0.0, sum(s.weight for s in minor_sins))

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
    # --required-return lets the investor override CAPM entirely with their
    # own required rate of return, bypassing the beta-driven Ke formula.
    cost_of_equity = required_return if required_return is not None else rf_rate + beta * erp
    cost_of_debt = 0.045
    tax_rate = 0.21
    after_tax_debt = cost_of_debt * (1 - tax_rate)

    # latest_debt/net_debt (and its cash/lease/reported-vs-computed
    # breakdown) are computed earlier now, ahead of the sins checklist -
    # see the "Net debt - moved ahead..." comment above.
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

    # ── Ordinary v3 (Step 4, spec Section 2.3): auto-switch DCF -> DDM ───
    # A dividend-paying company with a distorted capital structure (equity
    # <= 0, or leveraged past D/E 200%) gets a FCF-DCF fair value that's
    # artificially depressed by lease/debt obligations swallowing the WACC.
    # For that specific combination, switch to discounting the dividend
    # stream instead - overrides fair_value_share/over_under/val_status/
    # val_color_key in place so every existing consumer (portfolio_analyzer,
    # build_markdown_report, build_pdf_report) keeps reading the same keys
    # transparently; valuation_model tells the report renderers which
    # section to draw. Never triggers without diluted_shares data (no
    # fabricated near-zero DPS from a missing share count).
    valuation_model = "DCF"
    cagr_div = None
    dps_last = None
    info = data.get("info") or {}
    dividend_yield = info.get("dividendYield") or 0.0
    dividend_rate = info.get("dividendRate") or 0.0
    pays_dividends = dividend_yield > 0 or dividend_rate > 0
    debt_to_equity_ratio = (
        latest_debt / latest_equity if latest_equity > 0 and not pd.isna(latest_debt) else None
    )
    capital_distorted = latest_equity <= 0 or (debt_to_equity_ratio is not None and debt_to_equity_ratio > 2.0)
    use_ddm = pays_dividends and capital_distorted and not diluted_shares.isna().all()

    if use_ddm:
        dps_series = (cash_dividends_paid.abs() / diluted_shares).dropna()
        dps_window = dps_series.iloc[-4:] if len(dps_series) >= 2 else dps_series
        if len(dps_window) < 2 or dps_window.iloc[0] <= 0 or dps_window.iloc[-1] <= 0:
            cagr_div = 0.05
        else:
            n_periods = len(dps_window) - 1
            cagr_div = (dps_window.iloc[-1] / dps_window.iloc[0]) ** (1.0 / n_periods) - 1
            cagr_div = max(0.02, min(0.10, cagr_div))
        dps_last = dps_window.iloc[-1] if len(dps_window) else 0.0

        ddm_proj_dps = [dps_last * ((1 + cagr_div) ** t) for t in proj_years]
        ddm_pv_dividends = [ddm_proj_dps[t - 1] / ((1 + cost_of_equity) ** t) for t in proj_years]
        ddm_sum_pv = sum(ddm_pv_dividends)
        ddm_terminal_val = (
            ddm_proj_dps[-1] * (1 + terminal_g) / (cost_of_equity - terminal_g)
            if cost_of_equity > terminal_g else 0.0
        )
        ddm_pv_terminal = ddm_terminal_val / ((1 + cost_of_equity) ** 5)

        valuation_model = "DDM"
        fair_value_share = ddm_sum_pv + ddm_pv_terminal
        over_under = (fair_value_share - price) / price * 100 if price else 0.0
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
        "required_return_used": required_return is not None,
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
        # Ordinary v3 (Step 4): "DCF" unless the auto-switch above fired.
        "valuation_model": valuation_model,
        "cagr_div": cagr_div,
        "dps_last": dps_last,
        "debt_to_equity_ratio": debt_to_equity_ratio,
    }


# ── BANK-SPECIFIC ENGINE (Step 2, docs/spec/step2-bank-analyzer-implementation-spec.md) ──
# Commercial banks report interest income/expense, loans and deposits instead
# of revenue/current assets/FCF - the express sins checklist and CAPM/FCF-DCF
# above are mathematically invalid for them (spec Section 1). This is a
# parallel engine, not a variant of compute_metrics(): different checklist
# weights, different valuation models (DDM or ROE/P-B), never called from the
# Ordinary path.
BANK_MINOR_SIN_WEIGHTS = {
    "nii_declining": 1.0,
    "provision_spike": 1.0,
    "dilution": 1.0,
    "ltd_imbalance": 0.5,
    "dead_cash": 0.5,
    "negative_jaws": 0.5,
    "commissions_declining": 0.3,
    "net_income_declining": 0.3,
}
BANK_BUYBACK_BONUS_WEIGHT = -0.5
BANK_MAX_MINOR_SCORE = sum(BANK_MINOR_SIN_WEIGHTS.values())


def compute_bank_metrics(data, required_return=None):
    """Bank sins-checklist (spec Section 4) + DDM/ROE-P-B fair value (spec
    Section 5). Mirrors compute_metrics()'s output shape for the keys
    portfolio_analyzer.py and the report renderers actually read (sins/
    critical_sins/minor_sins/minor_score/max_minor_score/verdict/
    verdict_color_key/reasoning/price/fair_value_share/over_under_pct/
    val_status/val_color_key) so those callers work unmodified for banks;
    everything else is bank-specific (NII, LTD, DDM/ROE-P-B disclosure, ...).
    """
    df_fin = data["financials"]
    df_bal = data["balance"]
    df_cf = data["cashflow"]
    price = data["price"]
    shares = data["shares"]
    beta = data["beta"]
    info = data.get("info") or {}

    df_fin, df_bal, df_cf, year_labels = _align_statement_years(df_fin, df_bal, df_cf)

    # ── Section 3.1: Income statement ───────────────────────────────────
    interest_income = find_row(df_fin, ["Interest Income", "InterestIncome", "Interest Income Bank"])
    interest_expense = find_row(df_fin, ["Interest Expense", "InterestExpense", "Interest Expense Bank"])
    net_interest_income = find_row(df_fin, ["Net Interest Income", "NetInterestIncome"], default_val=float("nan"))
    if net_interest_income.isna().all():
        net_interest_income = interest_income - interest_expense
    commissions_income = find_row(df_fin, [
        "Fees and Commissions", "Net Fees and Income", "Commission Income",
        "Net Fee and Commission Income", "Fee Income and Other Non-Interest Income",
    ])
    trading_income = find_row(df_fin, [
        "Trading Revenue", "Investment Banking Income", "TradingAndInvestmentBankingIncome",
        "Trading Revenue and Other",
    ])
    credit_loss_provision = find_row(df_fin, [
        "Provision for Credit Losses", "Credit Loss Provision",
        "Provision For Doubtful Accounts", "Provision For Loan and Lease Losses",
    ])
    non_interest_expense = find_row(df_fin, [
        "Non Interest Expense", "Non-Interest Expense", "Total Non-Interest Expense",
        "Salaries and Employee Benefits",
    ])
    net_income = find_row(df_fin, ["Net Income", "NetIncome", "Net Income Common Stockholders"])
    preferred_dividends = find_row(df_fin, ["Preferred Stock Dividends", "Preferred Dividends"])
    diluted_shares = find_row(
        df_fin, ["Diluted Average Shares", "Diluted Shares Outstanding", "Average Shares"],
        default_val=float("nan"),
    )

    # ── Section 3.2: Balance sheet ──────────────────────────────────────
    # Missing-row default is NaN (not 0.0) for every balance-sheet line that
    # feeds a ratio or a critical check - yfinance's bank template genuinely
    # omits some of these for large banks (e.g. no dedicated "Total Deposits"
    # row for JPM/BAC), and a silent 0.0 would corrupt LTD/dead-cash math or
    # falsely fire equity_negative. NaN propagates to "insufficient data,
    # skip this check" everywhere below, never to an invented number.
    cash_and_equiv = find_row(df_bal, [
        "Cash and Cash Equivalents", "Cash Cash Equivalents and Short Term Investments",
        "CashAndCashEquivalents",
    ], default_val=float("nan"))
    trading_assets = find_row(df_bal, ["Trading Assets", "Trading Securities", "Trading Securities Assets"], default_val=float("nan"))
    htm_securities = find_row(df_bal, [
        "Held-to-Maturity Securities", "Held To Maturity Securities", "Securities Held To Maturity",
    ], default_val=float("nan"))
    # "Net Loan" (singular) is what yfinance actually calls this row for
    # diversified mega-banks (JPM, BAC) - not in the spec's literal keyword
    # list, added after live verification against real yfinance data so the
    # LTD/dead-cash checks and the structural table aren't needlessly N/A.
    net_loans = find_row(df_bal, ["Net Loans", "Net Loan", "Loans and Leases", "Gross Loans"], default_val=float("nan"))
    loan_loss_allowance = find_row(df_bal, [
        "Allowance for Credit Losses", "Reserve for Bad Loans", "Allowance For Loan And Lease Losses",
    ], default_val=float("nan"))
    total_deposits = find_row(df_bal, ["Total Deposits", "Deposits", "Demand Deposits"], default_val=float("nan"))
    total_borrowings = find_row(df_bal, ["Short Term Borrowings", "Long Term Debt", "Total Debt"], default_val=float("nan"))
    shareholders_equity = find_row(df_bal, [
        "Stockholders Equity", "Total Stockholders Equity", "Shareholders Equity",
    ], default_val=float("nan"))

    # ── Common dividends paid (for DDM DPS) ─────────────────────────────
    # yfinance has no dedicated "Common Dividends Paid" line for banks - only
    # a blended "Cash Dividends Paid" that includes preferred dividends.
    # preferred_dividends (fetched above per spec Section 3.1, "вычитаются
    # перед DDM") is subtracted here to isolate the common-only figure.
    cash_dividends_paid = find_row(df_cf, [
        "Common Stock Dividend Paid", "Cash Dividends Paid", "Payment Of Dividends",
    ], default_val=float("nan"))
    common_dividends_paid = cash_dividends_paid.abs() - preferred_dividends.abs()

    # ── FX bridge (Step 1 Currency Bridge, spec Section 3 preamble) ─────
    fx_rate = data.get("fx_rate", 1.0)
    if fx_rate != 1.0:
        interest_income = interest_income * fx_rate
        interest_expense = interest_expense * fx_rate
        net_interest_income = net_interest_income * fx_rate
        commissions_income = commissions_income * fx_rate
        trading_income = trading_income * fx_rate
        credit_loss_provision = credit_loss_provision * fx_rate
        non_interest_expense = non_interest_expense * fx_rate
        net_income = net_income * fx_rate
        preferred_dividends = preferred_dividends * fx_rate
        cash_and_equiv = cash_and_equiv * fx_rate
        trading_assets = trading_assets * fx_rate
        htm_securities = htm_securities * fx_rate
        net_loans = net_loans * fx_rate
        loan_loss_allowance = loan_loss_allowance * fx_rate
        total_deposits = total_deposits * fx_rate
        total_borrowings = total_borrowings * fx_rate
        shareholders_equity = shareholders_equity * fx_rate
        common_dividends_paid = common_dividends_paid * fx_rate

    latest_nii = net_interest_income.iloc[-1]
    latest_equity = shareholders_equity.iloc[-1]

    # ── Section 4.1: Critical sins (any one -> immediate SKIP) ──────────
    sins = []
    if not pd.isna(latest_nii) and latest_nii <= 0:
        sins.append(Sin(
            "nii_non_positive", "critical", 0.0,
            f"Чистый процентный убыток: NII последнего года ({latest_nii / 1e6:,.0f} млн) ≤ 0 - "
            "банк привлекает депозиты дороже, чем размещает кредиты.",
        ))
    if not pd.isna(latest_equity) and latest_equity <= 0:
        sins.append(Sin(
            "equity_negative", "critical", 0.0,
            f"Отрицательный регуляторный капитал: Shareholders Equity ({latest_equity / 1e6:,.0f} млн) ≤ 0 - "
            "угроза немедленного отзыва лицензии регулятором.",
        ))
    critical_sins = [s for s in sins if s.tier == "critical"]

    # ── Section 4.2: Minor sins ──────────────────────────────────────────
    # Per spec: any critical hit interrupts the detailed minor scoring, so
    # minor sins are only evaluated when no critical sin fired.
    ltd_ratio = None
    debt_to_equity = None
    if not critical_sins:
        if len(net_interest_income) >= 2 and net_interest_income.iloc[-1] < net_interest_income.iloc[-2]:
            sins.append(Sin(
                "nii_declining", "minor", BANK_MINOR_SIN_WEIGHTS["nii_declining"],
                f"Падение процентного дохода: NII с {net_interest_income.iloc[-2] / 1e6:,.0f} до "
                f"{net_interest_income.iloc[-1] / 1e6:,.0f} млн.",
            ))
        if (
            len(credit_loss_provision) >= 2
            and credit_loss_provision.iloc[-1] > 1.15 * credit_loss_provision.iloc[-2]
        ):
            sins.append(Sin(
                "provision_spike", "minor", BANK_MINOR_SIN_WEIGHTS["provision_spike"],
                f"Опасный рост резервов: Provision for Credit Losses вырос с "
                f"{credit_loss_provision.iloc[-2] / 1e6:,.0f} до {credit_loss_provision.iloc[-1] / 1e6:,.0f} млн "
                "(YoY > 15%).",
            ))
        if (
            not diluted_shares.isna().any()
            and len(diluted_shares) >= 2
            and diluted_shares.iloc[-2] != 0
        ):
            shares_ratio = diluted_shares.iloc[-1] / diluted_shares.iloc[-2]
            if shares_ratio > 1.015:
                sins.append(Sin(
                    "dilution", "minor", BANK_MINOR_SIN_WEIGHTS["dilution"],
                    f"Размытие долей акционеров: среднее число акций выросло с {diluted_shares.iloc[-2]:,.0f} "
                    f"до {diluted_shares.iloc[-1]:,.0f} ({(shares_ratio - 1) * 100:.1f}%).",
                ))
            elif shares_ratio < (1 / 1.015):
                sins.append(Sin(
                    "buyback_bonus", "minor", BANK_BUYBACK_BONUS_WEIGHT,
                    f"Бонус за байбэк: число акций сократилось с {diluted_shares.iloc[-2]:,.0f} "
                    f"до {diluted_shares.iloc[-1]:,.0f} ({(1 - shares_ratio) * 100:.1f}%).",
                ))
        latest_loans = net_loans.iloc[-1] if len(net_loans) else float("nan")
        latest_deposits = total_deposits.iloc[-1] if len(total_deposits) else float("nan")
        if not pd.isna(latest_loans) and not pd.isna(latest_deposits) and latest_deposits != 0:
            ltd_ratio = latest_loans / latest_deposits
            if ltd_ratio > 1.0 or ltd_ratio < 0.6:
                sins.append(Sin(
                    "ltd_imbalance", "minor", BANK_MINOR_SIN_WEIGHTS["ltd_imbalance"],
                    f"Дисбаланс Loan-to-Deposit: LTD = {ltd_ratio * 100:.1f}% "
                    f"({'выше 100%, риск дефицита ликвидности' if ltd_ratio > 1.0 else 'ниже 60%, пассивная работа с депозитами'}).",
                ))
        if (
            len(cash_and_equiv) >= 2 and len(net_loans) >= 2
            and not pd.isna(cash_and_equiv.iloc[-1]) and not pd.isna(cash_and_equiv.iloc[-2])
            and not pd.isna(net_loans.iloc[-1]) and not pd.isna(net_loans.iloc[-2])
            and cash_and_equiv.iloc[-1] > 1.30 * cash_and_equiv.iloc[-2]
            and net_loans.iloc[-1] < net_loans.iloc[-2]
        ):
            sins.append(Sin(
                "dead_cash", "minor", BANK_MINOR_SIN_WEIGHTS["dead_cash"],
                f"Накопление мёртвого кэша: денежные средства выросли с {cash_and_equiv.iloc[-2] / 1e6:,.0f} "
                f"до {cash_and_equiv.iloc[-1] / 1e6:,.0f} млн (>+30%), при этом кредитный портфель сократился.",
            ))
        net_op_income = net_interest_income + commissions_income
        if (
            len(non_interest_expense) >= 2 and len(net_op_income) >= 2
            and non_interest_expense.iloc[-2] != 0 and net_op_income.iloc[-2] != 0
        ):
            opex_growth = non_interest_expense.iloc[-1] / non_interest_expense.iloc[-2] - 1
            net_op_income_growth = net_op_income.iloc[-1] / net_op_income.iloc[-2] - 1
            if opex_growth > net_op_income_growth:
                sins.append(Sin(
                    "negative_jaws", "minor", BANK_MINOR_SIN_WEIGHTS["negative_jaws"],
                    f"Отрицательный JAWS: операционные расходы выросли на {opex_growth * 100:.1f}%, "
                    f"опережая рост NII+комиссий ({net_op_income_growth * 100:.1f}%).",
                ))
        if len(commissions_income) >= 2 and commissions_income.iloc[-1] < commissions_income.iloc[-2]:
            sins.append(Sin(
                "commissions_declining", "minor", BANK_MINOR_SIN_WEIGHTS["commissions_declining"],
                f"Падение комиссионных доходов: с {commissions_income.iloc[-2] / 1e6:,.0f} до "
                f"{commissions_income.iloc[-1] / 1e6:,.0f} млн.",
            ))
        if len(net_income) >= 2 and net_income.iloc[-1] < net_income.iloc[-2]:
            sins.append(Sin(
                "net_income_declining", "minor", BANK_MINOR_SIN_WEIGHTS["net_income_declining"],
                f"Падение чистой прибыли: с {net_income.iloc[-2] / 1e6:,.0f} до "
                f"{net_income.iloc[-1] / 1e6:,.0f} млн.",
            ))
        if not pd.isna(latest_equity) and latest_equity > 0 and not pd.isna(total_borrowings.iloc[-1]):
            debt_to_equity = total_borrowings.iloc[-1] / latest_equity

    minor_sins = [s for s in sins if s.tier == "minor"]
    minor_score = max(0.0, sum(s.weight for s in minor_sins))

    if critical_sins:
        verdict = "🔴 ПРОПУСТИТЬ / ВЫСОКИЙ РИСК"
        verdict_color_key = "danger"
        crit_labels = ", ".join(s.id for s in critical_sins)
        reasoning = (
            f"Обнаружен(ы) критический(е) банковский(е) фактор(ы) риска ({crit_labels}). "
            "Любой из них по отдельности делает инвестицию рискованной вне зависимости от прочих показателей."
        )
    elif minor_score <= 1.0:
        verdict = "🟢 КУПИТЬ / СИЛЬНЫЙ КАНДИДАТ"
        verdict_color_key = "success"
        reasoning = "Банк демонстрирует устойчивую динамику процентного дохода, качества кредитного портфеля и структуры фондирования. Риски минимальны."
    elif minor_score <= 2.5:
        verdict = "🟡 НАБЛЮДАТЬ / ОГРАНИЧЕННАЯ ДОЛЯ"
        verdict_color_key = "warning"
        reasoning = "Банк сохраняет жизнеспособную бизнес-модель, однако в динамике процентной маржи, резервов или структуры баланса присутствуют умеренные погрешности."
    else:
        verdict = "🔴 ПРОПУСТИТЬ / ВЫСОКИЙ РИСК"
        verdict_color_key = "danger"
        reasoning = (
            f"Взвешенный балл второстепенных банковских нарушений составил {minor_score:.1f} из "
            f"{BANK_MAX_MINOR_SCORE:.1f}. Совокупность этих факторов делает инвестицию рискованной на текущем этапе."
        )

    # ── Section 5: Fair value (DDM or ROE/P-B) ──────────────────────────
    def _cost_of_equity():
        if required_return is not None:
            return required_return
        ke = 0.04 + beta * 0.05
        return max(0.05, min(0.15, ke))

    cost_of_equity = _cost_of_equity()
    terminal_g = 0.025

    dividend_yield = info.get("dividendYield") or 0.0
    latest_common_div_paid = (
        common_dividends_paid.iloc[-1] if len(common_dividends_paid) and not pd.isna(common_dividends_paid.iloc[-1])
        else 0.0
    )
    pays_dividends = latest_common_div_paid > 0 or dividend_yield > 0

    bvps = None
    roe = None
    cagr_div = None
    dps_last = None
    dps_series = None

    if pays_dividends and not diluted_shares.isna().all():
        dps_series = (common_dividends_paid / diluted_shares).dropna()
        dps_window = dps_series.iloc[-4:] if len(dps_series) >= 2 else dps_series
        if len(dps_window) < 2 or dps_window.iloc[0] <= 0 or dps_window.iloc[-1] <= 0:
            cagr_div = 0.03
        else:
            n_periods = len(dps_window) - 1
            cagr_div = (dps_window.iloc[-1] / dps_window.iloc[0]) ** (1.0 / n_periods) - 1
            cagr_div = max(0.01, min(0.08, cagr_div))
        dps_last = dps_window.iloc[-1] if len(dps_window) else 0.0

        proj_years = list(range(1, 6))
        proj_dps = [dps_last * ((1 + cagr_div) ** t) for t in proj_years]
        pv_dividends = [proj_dps[t - 1] / ((1 + cost_of_equity) ** t) for t in proj_years]
        sum_pv_dividends = sum(pv_dividends)
        terminal_val = (
            proj_dps[-1] * (1 + terminal_g) / (cost_of_equity - terminal_g)
            if cost_of_equity > terminal_g else 0.0
        )
        pv_terminal_val = terminal_val / ((1 + cost_of_equity) ** 5)
        fair_value_share = sum_pv_dividends + pv_terminal_val
        valuation_model = "DDM"
    else:
        valuation_model = "ROE_PB"
        if pd.isna(latest_equity) or latest_equity <= 0 or shares <= 0:
            bvps = 0.0
            roe = 0.0
            fair_value_share = 0.0
        else:
            bvps = latest_equity / shares
            latest_net_income = net_income.iloc[-1]
            roe = latest_net_income / latest_equity
            if roe <= 0:
                fair_value_share = 0.1 * bvps
            else:
                fair_value_share = bvps * (roe / cost_of_equity)

    over_under = (fair_value_share - price) / price * 100 if price else 0.0
    if over_under > 10.0:
        val_status = f"НЕДООЦЕНЕНА на {abs(over_under):.1f}% (Потенциал роста)"
        val_color_key = "success"
    elif over_under < -10.0:
        val_status = f"ПЕРЕОЦЕНЕНА на {abs(over_under):.1f}% (Завышенная стоимость)"
        val_color_key = "danger"
    else:
        val_status = f"ОЦЕНЕНА СПРАВЕДЛИВО (Отклонение {over_under:.1f}%)"
        val_color_key = "warning"

    return {
        "kind": "bank",
        "year_labels": year_labels,
        "interest_income": interest_income,
        "interest_expense": interest_expense,
        "net_interest_income": net_interest_income,
        "commissions_income": commissions_income,
        "trading_income": trading_income,
        "credit_loss_provision": credit_loss_provision,
        "non_interest_expense": non_interest_expense,
        "net_income": net_income,
        "preferred_dividends": preferred_dividends,
        "cash_and_equiv": cash_and_equiv,
        "trading_assets": trading_assets,
        "htm_securities": htm_securities,
        "net_loans": net_loans,
        "loan_loss_allowance": loan_loss_allowance,
        "total_deposits": total_deposits,
        "total_borrowings": total_borrowings,
        "shareholders_equity": shareholders_equity,
        "diluted_shares": diluted_shares,
        "ltd_ratio": ltd_ratio,
        "debt_to_equity": debt_to_equity,
        "sins": sins,
        "critical_sins": critical_sins,
        "minor_sins": minor_sins,
        "minor_score": minor_score,
        "max_minor_score": BANK_MAX_MINOR_SCORE,
        "verdict": verdict,
        "verdict_color_key": verdict_color_key,
        "reasoning": reasoning,
        "beta": beta,
        "cost_of_equity": cost_of_equity,
        "required_return_used": required_return is not None,
        "valuation_model": valuation_model,
        "cagr_div": cagr_div,
        "dps_last": dps_last,
        "bvps": bvps,
        "roe": roe,
        "price": price,
        "fair_value_share": fair_value_share,
        "over_under_pct": over_under,
        "val_status": val_status,
        "val_color_key": val_color_key,
        "current_ratio": None,
        "net_margin_pct": None,
    }


# ── REIT-SPECIFIC ENGINE (Step 3, docs/spec/step3-reit-analyzer-implementation-spec.md) ──
# REITs' Net Income is artificially depressed by real-estate depreciation
# (a paper charge that doesn't reflect actual cash economics), and standard
# FCF-based DCF is meaningless for a business that's structurally a pass-
# through of rental cash flow - see spec Section 0/2. This is a third
# parallel engine (after Ordinary/Bank): FFO/AFFO/NOI checklist, NAV
# (Net Asset Value) fair value instead of DCF.
REIT_MINOR_SIN_WEIGHTS = {
    "affo_declining": 1.0,
    "occupancy_declining": 1.0,
    "dilution": 1.0,
    "high_leverage": 0.5,
    "noi_declining": 0.5,
    "capex_ratio_growth": 0.3,
}
REIT_BUYBACK_BONUS_WEIGHT = -0.5
REIT_MAX_MINOR_SCORE = sum(REIT_MINOR_SIN_WEIGHTS.values())

REIT_CAP_RATE_MATRIX = [
    (("industrial", "logistic", "warehouse"), 0.055, "Industrial / Logistics"),
    (("residential", "apartment"), 0.060, "Residential"),
    (("healthcare", "medical", "health care"), 0.065, "Healthcare / Medical"),
    (("office", "retail", "mall"), 0.070, "Office / Retail / Malls"),
]
REIT_DEFAULT_CAP_RATE = 0.065
REIT_DEFAULT_CAP_RATE_LABEL = "Default"


def _reit_cap_rate(info):
    """Cap Rate lookup (spec Section 5.1) - an explicit info['capRate'] first
    (yfinance never actually populates this, but the spec asks to check),
    then a conservative median-by-specialization matrix keyed off industry/
    sector keywords, first match wins. Never invents a company-specific
    rate beyond this - real REITs report their own portfolio cap rate in
    investor materials, not through yfinance."""
    info = info or {}
    explicit = info.get("capRate")
    if explicit:
        return float(explicit), "Explicit (info.capRate)"
    haystack = " ".join(str(info.get(k) or "") for k in ("industry", "sector", "longBusinessSummary")).lower()
    for keywords, rate, label in REIT_CAP_RATE_MATRIX:
        if any(kw in haystack for kw in keywords):
            return rate, label
    return REIT_DEFAULT_CAP_RATE, REIT_DEFAULT_CAP_RATE_LABEL


def compute_reit_metrics(data, required_return=None):
    """REIT sins-checklist (spec Section 4) + NAV fair value (spec Section
    5). Mirrors compute_bank_metrics()'s output shape for the keys
    portfolio_analyzer.py and the report renderers read in common
    (sins/critical_sins/minor_sins/minor_score/max_minor_score/verdict/
    verdict_color_key/reasoning/price/fair_value_share/over_under_pct/
    val_status/val_color_key); everything else is REIT-specific (FFO/AFFO/
    NOI, Occupancy, Cap Rate, NAV bridge).

    Unlike compute_bank_metrics(), a critical sin here does NOT skip minor
    scoring - spec Section 4 has no "interrupts detailed scoring" language
    for REIT (unlike Bank's Section 4.1), so minor sins are always computed
    in full, same as Ordinary's compute_metrics().
    """
    df_fin = data["financials"]
    df_bal = data["balance"]
    df_cf = data["cashflow"]
    price = data["price"]
    shares = data["shares"]
    beta = data["beta"]
    info = data.get("info") or {}

    df_fin, df_bal, df_cf, year_labels = _align_statement_years(df_fin, df_bal, df_cf)

    # ── Section 3: yfinance row mapping ─────────────────────────────────
    d_and_a = find_row(df_cf, ["Depreciation And Amortization", "Depreciation & Amortization", "Depreciation"])
    gain_on_sale = find_row(df_cf, [
        "Gain on Sale of Real Estate", "Gain on Sale of Investment Property", "Gain on Sale of Business",
    ])
    capex = find_row(df_cf, ["Capital Expenditure", "Capital Expenditures", "CapEx"])
    net_income = find_row(df_fin, ["Net Income", "NetIncome", "Net Income Common Stockholders"])
    rental_revenue = find_row(df_fin, ["Rental Revenue", "Total Revenue", "Revenue"])
    property_opex = find_row(df_fin, [
        "Property Operating Expense", "Property Expenses", "Operating Expense", "Operating Expenses",
    ])
    re_taxes = find_row(df_fin, ["Real Estate Taxes", "Property Taxes", "Taxes Other Than Income Taxes"])
    diluted_shares = find_row(
        df_fin, ["Diluted Average Shares", "Diluted Shares Outstanding", "Average Shares"],
        default_val=float("nan"),
    )
    construction_in_progress = find_row(df_bal, ["Construction In Progress", "Capital Work In Progress", "CIP"])
    receivables = find_row(df_bal, ["Receivables", "Accounts Receivable", "Net Receivables"])
    cash = find_row(df_bal, [
        "Cash and Cash Equivalents", "Cash Cash Equivalents and Short Term Investments", "CashAndCashEquivalents",
    ])
    total_liab = find_row(df_bal, ["Total Liabilities Net Minority Interest", "Total Liabilities"], default_val=float("nan"))
    total_debt = find_row(df_bal, ["Total Debt", "Long Term Debt"], default_val=float("nan"))
    shareholders_equity = find_row(df_bal, [
        "Stockholders Equity", "Total Stockholders Equity", "Shareholders Equity",
    ], default_val=float("nan"))
    # "Cash Dividends Paid" preferred over "Common Stock Dividend Paid" -
    # live-verified against SPG, where yfinance's "Common Stock Dividend
    # Paid" line (-$439M) is a small fraction of the real total ($3.23B,
    # matching dividendRate x shares) with the rest oddly bucketed under
    # "Preferred Stock Dividend Paid" (SPG has no preferred stock anywhere
    # near that size - an OP-unit/UPREIT structure quirk in yfinance's
    # generic template, not an actual preferred dividend). "Cash Dividends
    # Paid" matched dividendRate x shares correctly for all three of O/SPG/
    # PLD tested in Step 3, so it's the more reliable primary source here.
    dividends_paid = find_row(df_cf, [
        "Cash Dividends Paid", "Common Stock Dividend Paid", "Payment Of Dividends",
    ], default_val=float("nan")).abs()

    occupancy_rate = info.get("occupancy") or info.get("occupancyRate")
    if occupancy_rate is None:
        print(
            f"  [{data.get('ticker', '?')}] Occupancy Rate недоступен в yfinance.info - "
            "используется консервативный дефолт 95.0%."
        )
        occupancy_rate = 0.95
    else:
        occupancy_rate = float(occupancy_rate)

    # ── FX bridge ────────────────────────────────────────────────────────
    fx_rate = data.get("fx_rate", 1.0)
    if fx_rate != 1.0:
        d_and_a = d_and_a * fx_rate
        gain_on_sale = gain_on_sale * fx_rate
        capex = capex * fx_rate
        net_income = net_income * fx_rate
        rental_revenue = rental_revenue * fx_rate
        property_opex = property_opex * fx_rate
        re_taxes = re_taxes * fx_rate
        construction_in_progress = construction_in_progress * fx_rate
        receivables = receivables * fx_rate
        cash = cash * fx_rate
        total_liab = total_liab * fx_rate
        total_debt = total_debt * fx_rate
        shareholders_equity = shareholders_equity * fx_rate
        dividends_paid = dividends_paid * fx_rate

    # ── Section 2: FFO / AFFO / NOI ──────────────────────────────────────
    ffo = net_income + d_and_a - gain_on_sale
    affo = ffo - capex.abs()
    noi = rental_revenue - property_opex - re_taxes

    latest_equity = shareholders_equity.iloc[-1]
    latest_affo = affo.iloc[-1]
    latest_dividends = dividends_paid.iloc[-1] if not pd.isna(dividends_paid.iloc[-1]) else 0.0

    # ── Section 4.1: Critical sins ───────────────────────────────────────
    sins = []
    affo_payout_ratio = None
    if latest_dividends > 0:
        if latest_affo <= 0:
            affo_payout_ratio = float("inf")
            sins.append(Sin(
                "affo_payout_over_100", "critical", 0.0,
                f"Дивиденды «в долг»: выплачены дивиденды ({latest_dividends / 1e6:,.0f} млн) при "
                f"AFFO ≤ 0 ({latest_affo / 1e6:,.0f} млн) - выплата не обеспечена денежным потоком.",
            ))
        else:
            affo_payout_ratio = latest_dividends / latest_affo
            if affo_payout_ratio > 1.0:
                sins.append(Sin(
                    "affo_payout_over_100", "critical", 0.0,
                    f"Дивиденды «в долг»: AFFO Payout Ratio = {affo_payout_ratio * 100:.1f}% (> 100%) - "
                    "траст выплачивает больше, чем зарабатывает по AFFO.",
                ))
    if occupancy_rate < 0.80:
        sins.append(Sin(
            "occupancy_below_80", "critical", 0.0,
            f"Низкая заполняемость объектов: Occupancy Rate = {occupancy_rate * 100:.1f}% (< 80%).",
        ))
    if not pd.isna(latest_equity) and latest_equity <= 0:
        sins.append(Sin(
            "equity_negative", "critical", 0.0,
            f"Отрицательный акционерный капитал: Shareholders Equity ({latest_equity / 1e6:,.0f} млн) ≤ 0.",
        ))
    critical_sins = [s for s in sins if s.tier == "critical"]

    # ── Section 4.2: Minor sins (always computed - no interruption here) ─
    if len(affo) >= 2 and affo.iloc[-2] > 0 and affo.iloc[-1] > 0 and affo.iloc[-1] < affo.iloc[-2]:
        sins.append(Sin(
            "affo_declining", "minor", REIT_MINOR_SIN_WEIGHTS["affo_declining"],
            f"Падение AFFO: с {affo.iloc[-2] / 1e6:,.0f} до {affo.iloc[-1] / 1e6:,.0f} млн.",
        ))
    # Note: occupancy_declining (spec Section 4.2) is not evaluated here -
    # occupancy_rate above is a single current-snapshot value (yfinance
    # carries no historical Occupancy Rate time series), so there is no
    # prior-year figure to compare against without inventing one.
    debt_to_equity = None
    if (
        not diluted_shares.isna().any()
        and len(diluted_shares) >= 2
        and diluted_shares.iloc[-2] != 0
    ):
        shares_ratio = diluted_shares.iloc[-1] / diluted_shares.iloc[-2]
        if shares_ratio > 1.025:
            sins.append(Sin(
                "dilution", "minor", REIT_MINOR_SIN_WEIGHTS["dilution"],
                f"Размытие капитала через SPO: среднее число акций выросло с {diluted_shares.iloc[-2]:,.0f} "
                f"до {diluted_shares.iloc[-1]:,.0f} ({(shares_ratio - 1) * 100:.1f}%).",
            ))
        elif shares_ratio < (1 / 1.015):
            sins.append(Sin(
                "buyback_bonus", "minor", REIT_BUYBACK_BONUS_WEIGHT,
                f"Бонус за байбэк: число акций сократилось с {diluted_shares.iloc[-2]:,.0f} "
                f"до {diluted_shares.iloc[-1]:,.0f} ({(1 - shares_ratio) * 100:.1f}%).",
            ))
    if not pd.isna(latest_equity) and latest_equity > 0 and not pd.isna(total_debt.iloc[-1]):
        debt_to_equity = total_debt.iloc[-1] / latest_equity
        if debt_to_equity > 2.0:
            sins.append(Sin(
                "high_leverage", "minor", REIT_MINOR_SIN_WEIGHTS["high_leverage"],
                f"Критический долг: Total Debt / Shareholders Equity = {debt_to_equity * 100:.1f}% (> 200%).",
            ))
    if len(noi) >= 2 and noi.iloc[-1] < noi.iloc[-2]:
        sins.append(Sin(
            "noi_declining", "minor", REIT_MINOR_SIN_WEIGHTS["noi_declining"],
            f"Падение NOI: с {noi.iloc[-2] / 1e6:,.0f} до {noi.iloc[-1] / 1e6:,.0f} млн.",
        ))
    if len(capex) >= 2 and len(ffo) >= 2 and ffo.iloc[-2] > 0 and ffo.iloc[-1] > 0:
        capex_ratio_prior = capex.iloc[-2].__abs__() / ffo.iloc[-2]
        capex_ratio_current = capex.iloc[-1].__abs__() / ffo.iloc[-1]
        if capex_ratio_prior > 0 and (capex_ratio_current / capex_ratio_prior - 1) > 0.05:
            sins.append(Sin(
                "capex_ratio_growth", "minor", REIT_MINOR_SIN_WEIGHTS["capex_ratio_growth"],
                f"Рост доли капинвестиций: CapEx/FFO вырос с {capex_ratio_prior * 100:.1f}% до "
                f"{capex_ratio_current * 100:.1f}% (YoY > 5%).",
            ))

    minor_sins = [s for s in sins if s.tier == "minor"]
    minor_score = max(0.0, sum(s.weight for s in minor_sins))

    if critical_sins:
        verdict = "🔴 ПРОПУСТИТЬ / ВЫСОКИЙ РИСК"
        verdict_color_key = "danger"
        crit_labels = ", ".join(s.id for s in critical_sins)
        reasoning = (
            f"Обнаружен(ы) критический(е) фактор(ы) риска REIT ({crit_labels}). "
            "Любой из них по отдельности делает инвестицию рискованной вне зависимости от прочих показателей."
        )
    elif minor_score <= 1.0:
        verdict = "🟢 КУПИТЬ / СИЛЬНЫЙ КАНДИДАТ"
        verdict_color_key = "success"
        reasoning = "Траст демонстрирует устойчивый рост AFFO/NOI, комфортную заполняемость объектов и разумную долговую нагрузку. Риски минимальны."
    elif minor_score <= 2.5:
        verdict = "🟡 НАБЛЮДАТЬ / ОГРАНИЧЕННАЯ ДОЛЯ"
        verdict_color_key = "warning"
        reasoning = "Портфель недвижимости остаётся жизнеспособным, однако в динамике AFFO, NOI или долговой нагрузки присутствуют умеренные погрешности."
    else:
        verdict = "🔴 ПРОПУСТИТЬ / ВЫСОКИЙ РИСК"
        verdict_color_key = "danger"
        reasoning = (
            f"Взвешенный балл второстепенных нарушений REIT составил {minor_score:.1f} из "
            f"{REIT_MAX_MINOR_SCORE:.1f}. Совокупность этих факторов делает инвестицию рискованной на текущем этапе."
        )

    # ── Section 5: NAV fair value ────────────────────────────────────────
    cap_rate, cap_rate_label = _reit_cap_rate(info)
    latest_noi = noi.iloc[-1]
    property_value = latest_noi / cap_rate if cap_rate else 0.0
    latest_cash = cash.iloc[-1] if not pd.isna(cash.iloc[-1]) else 0.0
    latest_receivables = receivables.iloc[-1] if not pd.isna(receivables.iloc[-1]) else 0.0
    latest_cip = construction_in_progress.iloc[-1] if not pd.isna(construction_in_progress.iloc[-1]) else 0.0
    latest_total_liab = total_liab.iloc[-1] if not pd.isna(total_liab.iloc[-1]) else 0.0
    nav = property_value + latest_cash + latest_receivables + latest_cip - latest_total_liab
    fair_value_share = nav / shares if shares > 0 else 0.0

    over_under = (fair_value_share - price) / price * 100 if price else 0.0
    if over_under > 10.0:
        val_status = f"НЕДООЦЕНЕНА на {abs(over_under):.1f}% (Потенциал роста)"
        val_color_key = "success"
    elif over_under < -10.0:
        val_status = f"ПЕРЕОЦЕНЕНА на {abs(over_under):.1f}% (Завышенная стоимость)"
        val_color_key = "danger"
    else:
        val_status = f"ОЦЕНЕНА СПРАВЕДЛИВО (Отклонение {over_under:.1f}%)"
        val_color_key = "warning"

    latest_ffo = ffo.iloc[-1]
    latest_diluted_shares = (
        diluted_shares.iloc[-1] if len(diluted_shares) and not pd.isna(diluted_shares.iloc[-1]) else shares
    )
    ffo_per_share = latest_ffo / latest_diluted_shares if latest_diluted_shares else None
    p_ffo = price / ffo_per_share if ffo_per_share and ffo_per_share > 0 else None

    return {
        "kind": "reit",
        "year_labels": year_labels,
        "d_and_a": d_and_a,
        "gain_on_sale": gain_on_sale,
        "capex": capex,
        "net_income": net_income,
        "rental_revenue": rental_revenue,
        "property_opex": property_opex,
        "re_taxes": re_taxes,
        "construction_in_progress": construction_in_progress,
        "receivables": receivables,
        "cash": cash,
        "total_liab": total_liab,
        "total_debt": total_debt,
        "shareholders_equity": shareholders_equity,
        "diluted_shares": diluted_shares,
        "dividends_paid": dividends_paid,
        "ffo": ffo,
        "affo": affo,
        "noi": noi,
        "occupancy_rate": occupancy_rate,
        "affo_payout_ratio": affo_payout_ratio,
        "debt_to_equity": debt_to_equity,
        "cap_rate": cap_rate,
        "cap_rate_label": cap_rate_label,
        "property_value": property_value,
        "nav": nav,
        "ffo_per_share": ffo_per_share,
        "p_ffo": p_ffo,
        "sins": sins,
        "critical_sins": critical_sins,
        "minor_sins": minor_sins,
        "minor_score": minor_score,
        "max_minor_score": REIT_MAX_MINOR_SCORE,
        "verdict": verdict,
        "verdict_color_key": verdict_color_key,
        "reasoning": reasoning,
        "beta": beta,
        "price": price,
        "fair_value_share": fair_value_share,
        "over_under_pct": over_under,
        "val_status": val_status,
        "val_color_key": val_color_key,
        "current_ratio": None,
        "net_margin_pct": None,
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


def required_return_type(value):
    """argparse `type=` for --required-return. Fails fast (during parse_args(),
    before any network call) rather than silently clamping - a clamped
    out-of-range value (e.g. a `15` typo instead of `0.15`) would produce a
    plausible-looking but silently wrong fair value with no indication
    anything went wrong. Shared by financial_analyzer.py and
    portfolio_analyzer.py so the validation behavior never drifts between them.
    """
    try:
        fvalue = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Требуемая доходность должна быть числом. Получено: '{value}'")
    if fvalue > 1.0:
        suggested = fvalue / 100.0
        raise argparse.ArgumentTypeError(
            f"Некорректное значение: {value}. Параметр --required-return должен быть долей от единицы "
            f"(например, 0.15, а не 15). Возможно, вы имели в виду {suggested:.3f}?"
        )
    if not (0.05 <= fvalue <= 0.25):
        raise argparse.ArgumentTypeError(
            f"Требуемая доходность должна быть в диапазоне 0.05-0.25 (5%-25%). Получено: {fvalue}."
        )
    return fvalue


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


def build_markdown_report(
    ticker, data, m, forward_outlook=None, catalysts_text=None,
    excluded_sector=None, excluded_industry=None,
):
    """Plain-text/Markdown twin of the PDF report - same numbers, no charts."""
    name = data["name"]
    trading_ccy = data.get("trading_currency", "USD")
    financial_ccy = data.get("financial_currency", "USD")
    forward_outlook = forward_outlook or dict(_EMPTY_FORWARD_OUTLOOK)
    catalysts_text = catalysts_text or CATALYSTS_PLACEHOLDER
    catalysts_block = "\n".join(
        f"> {line}" if line.strip() else ">" for line in catalysts_text.splitlines()
    )
    sector_warning_line = (
        f"> ⚠️ **ВНИМАНИЕ (НЕПРИМЕНИМАЯ МЕТОДИКА):** Компания относится к сектору "
        f"**{excluded_sector} ({excluded_industry})**. Экспресс-оценка ликвидности (Current Ratio) и "
        "классический расчет справедливой цены по DCF для данного сектора могут быть некорректны и "
        "давать ложные результаты!\n\n"
        if excluded_sector else ""
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
    ke_disclosure = (
        f"Ke = задано инвестором (--required-return) = {m['cost_of_equity'] * 100:.2f}%"
        if m["required_return_used"]
        else f"Ke = Rf + β×ERP = 4% + {m['beta']:.2f}×5% = {m['cost_of_equity'] * 100:.2f}%"
    )

    # Ordinary v3 (Step 4): a dividend-paying company with a distorted
    # capital structure (equity<=0 or D/E>200%) gets valued by DDM instead
    # of DCF - see compute_metrics()'s "Ordinary v3" section. m["fair_value_share"]/
    # over_under_pct/val_status already reflect whichever model ran; only the
    # disclosure text below needs to branch, since the DCF-only concepts
    # (WACC, Enterprise Value, sensitivity matrix) don't apply to DDM.
    if m.get("valuation_model") == "DDM":
        section3_md = f"""## 3. Оценка справедливой стоимости (Модель DDM)

⚠️ **Внимание:** Применена модель дисконтирования дивидендов (DDM) вместо классического DCF - у компании искажена структура капитала (отрицательный или "перегруженный" долгом акционерный капитал) на фоне стабильной истории дивидендных выплат. Классический FCF-DCF в этом случае занижает стоимость (лизинговые/долговые обязательства искажают WACC).

- {ke_disclosure}
- Темп роста дивидендов (CAGR_div, ограничен 2.0%-10.0%): {m['cagr_div'] * 100:.2f}%
- DPS последнего года (Dividends Paid / Diluted Shares): {m['dps_last']:.2f} {trading_ccy}
- Терминальный темп роста (Gordon Growth): 2.5%

**Справедливая стоимость по DDM: {m['fair_value_share']:.2f} {trading_ccy}**
Текущая рыночная цена: {m['price']:.2f} {trading_ccy} ({data['price_kind']}, {data['quote_time_label']}) | Статус: **{m['val_status']}**
"""
    else:
        section3_md = f"""## 3. Модель дисконтирования денежных потоков (DCF)

- Стоимость собственного капитала: {ke_disclosure}
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
"""

    md = f"""{sector_warning_line}# Фундаментальный анализ & оценка DCF: {ticker.upper()}

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

{section3_md}
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


def build_pdf_report(
    ticker, retries=5, retry_delay=5, allow_sample=False, catalysts_text=None, force=False,
    required_return=None,
):
    data = get_company_data(ticker, retries=retries, retry_delay=retry_delay, allow_sample=allow_sample)
    excluded_sector, excluded_industry = check_sector_suitability(ticker, data.get("info", {}), force)
    m = compute_metrics(data, required_return=required_return)
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

    if excluded_sector:
        sector_warning_style = ParagraphStyle(
            "SectorWarning", fontName=FONT_BOLD, fontSize=10, textColor=COLORS["white"], leading=14,
        )
        sector_warning_text = (
            "⚠ ВНИМАНИЕ (НЕПРИМЕНИМАЯ МЕТОДИКА): Компания относится к сектору "
            f"<b>{escape_xml(excluded_sector)} ({escape_xml(excluded_industry)})</b>. Экспресс-оценка "
            "ликвидности (Current Ratio) и классический расчет справедливой цены по DCF для данного "
            "сектора могут быть некорректны и давать ложные результаты!"
        )
        story.append(SectorWarningBanner(sector_warning_text, USABLE_W, COLORS, sector_warning_style))
        story.append(Spacer(1, 10))

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

    # ── SECTION 3: FAIR VALUE (DCF, or DDM for Ordinary v3 - Step 4) ─────
    # See build_markdown_report()'s twin branch and compute_metrics()'s
    # "Ordinary v3" section for why/when DDM replaces DCF here - m["fair_
    # value_share"]/val_status already reflect whichever model ran.
    if m.get("valuation_model") == "DDM":
        story.append(Paragraph("3. Оценка справедливой стоимости (Модель DDM)", h1_style))
        story.append(
            Paragraph(
                "⚠️ Применена модель дисконтирования дивидендов (DDM) вместо классического DCF - у компании "
                "искажена структура капитала (отрицательный или «перегруженный» долгом акционерный капитал) на фоне "
                "стабильной истории дивидендных выплат. Классический FCF-DCF в этом случае занижает стоимость "
                "(лизинговые/долговые обязательства искажают WACC).",
                body_style,
            )
        )
        ke_disclosure = (
            f"Ke = задано инвестором (--required-return) = {cost_of_equity * 100:.2f}%"
            if m["required_return_used"]
            else f"Ke = Rf + β×ERP = 4% + {beta:.2f}×5% = {cost_of_equity * 100:.2f}%"
        )
        ddm_info_text = (
            f"• <b>Стоимость собственного капитала:</b> {ke_disclosure}<br/>"
            f"• <b>Темп роста дивидендов (CAGR_div, ограничен 2.0%-10.0%):</b> {m['cagr_div'] * 100:.2f}%<br/>"
            f"• <b>DPS последнего года (Dividends Paid / Diluted Shares):</b> {m['dps_last']:.2f} {trading_ccy}<br/>"
            f"• <b>Терминальный темп роста (Gordon Growth):</b> 2.5%<br/>"
        )
        story.append(CalloutBox(ddm_info_text, USABLE_W, COLORS, callout_text_style, COLORS["accent"]))
        story.append(Spacer(1, 8))

        val_banner_text = (
            f"<b>СПРАВЕДЛИВАЯ СТОИМОСТЬ ПО DDM: {fair_value_share:.2f} {trading_ccy}</b><br/>"
            f"Текущая рыночная цена: {price:.2f} {trading_ccy} ({price_kind}, {quote_time_label}) "
            f"| Статус: <font color='{val_color.hexval()}'><b>{val_status}</b></font>"
        )
        story.append(
            CalloutBox(
                val_banner_text, USABLE_W, COLORS,
                ParagraphStyle("ValB", parent=callout_text_style, fontSize=10, leading=14),
                val_color,
            )
        )
        story.append(Spacer(1, 12))
    else:
        story.append(Paragraph("3. Модель дисконтирования денежных потоков (DCF)", h1_style))
        story.append(
            Paragraph(
                "Расчет справедливой стоимости на основе темпов роста FCF и средневзвешенной стоимости капитала (WACC):",
                body_style,
            )
        )

        debt_html = "<br/>".join(f"• <b>{label}:</b> {value}" for label, value in debt_lines)
        ke_disclosure = (
            f"Ke = задано инвестором (--required-return) = {cost_of_equity * 100:.2f}%"
            if m["required_return_used"]
            else f"Ke = Rf + β×ERP = 4% + {beta:.2f}×5% = {cost_of_equity * 100:.2f}%"
        )
        dcf_info_text = (
            f"• <b>Стоимость собственного капитала:</b> {ke_disclosure}<br/>"
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

    md_filename = build_markdown_report(
        ticker, data, m, forward_outlook, catalysts_text, excluded_sector, excluded_industry,
    )
    print(f"Success! Markdown report saved to: {md_filename}")

    return pdf_filename, md_filename


# ── BANK REPORT RENDERERS (Step 2, spec Section 6) ──────────────────────
# No WACC/Enterprise Value/Net Debt charts or tables here - the classical
# DCF machinery above is simply not built for banks (spec Section 1).
def _bank_valuation_disclosure(m):
    """Plain (label, value) pairs for the DDM/ROE-P-B model disclosure -
    shared between the PDF and Markdown bank renderers (spec Section 6.2)."""
    ke_line = (
        f"Ke = задано инвестором (--required-return) = {m['cost_of_equity'] * 100:.2f}%"
        if m["required_return_used"]
        else f"Ke = Rf + β×ERP = 4% + {m['beta']:.2f}×5% = {m['cost_of_equity'] * 100:.2f}%"
    )
    if m["valuation_model"] == "DDM":
        return "Модель дисконтирования дивидендов (DDM)", [
            (ke_line, ""),
            ("Темп роста дивидендов (CAGR_div, ограничен 1.0%-8.0%)", f"{m['cagr_div'] * 100:.2f}%"),
            ("DPS последнего года (Common Dividends Paid / Diluted Shares)", f"{m['dps_last']:.2f} USD"),
            ("Терминальный темп роста (Gordon Growth)", "2.5%"),
        ]
    return "Модель рентабельности капитала (ROE / P/B)", [
        (ke_line, ""),
        ("Балансовая стоимость на акцию (BVPS)", f"{m['bvps']:.2f} USD"),
        ("Рентабельность капитала (ROE)", f"{m['roe'] * 100:.2f}%"),
    ]


def _bank_structural_rows(m, trading_ccy):
    """Loan-portfolio / deposit-base YoY table (spec Section 6.3). 'N/A' for
    any row yfinance doesn't expose for this bank - never a fabricated 0."""
    def fmt(series):
        return [
            "N/A" if pd.isna(v) else f"{v / 1e6:,.1f}"
            for v in series
        ]

    rows = [
        ["Net Loans (млн.)"] + fmt(m["net_loans"]),
        ["Allowance for Credit Losses (млн.)"] + fmt(m["loan_loss_allowance"]),
        ["Total Deposits (млн.)"] + fmt(m["total_deposits"]),
        ["LTD Ratio"] + [
            "N/A" if pd.isna(l) or pd.isna(d) or d == 0 else f"{(l / d) * 100:.1f}%"
            for l, d in zip(m["net_loans"], m["total_deposits"])
        ],
    ]
    return rows


def build_bank_markdown_report(ticker, data, m, catalysts_text=None):
    """Bank twin of build_markdown_report() - NII/LTD in the header, DDM or
    ROE/P-B valuation disclosure instead of WACC/DCF, loan/deposit
    structural table instead of the Ordinary current-assets table."""
    name = data["name"]
    trading_ccy = data.get("trading_currency", "USD")
    financial_ccy = data.get("financial_currency", "USD")
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
        return f"| {label} | " + " | ".join(
            "N/A" if pd.isna(v) else fmt.format(v) for v in series
        ) + " |"

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

    model_name, model_lines = _bank_valuation_disclosure(m)
    model_block = "\n".join(f"- {label}{': ' + value if value else ''}" for label, value in model_lines)
    ltd_txt = "N/A" if m["ltd_ratio"] is None else f"{m['ltd_ratio'] * 100:.1f}%"
    de_txt = "N/A" if m["debt_to_equity"] is None else f"{m['debt_to_equity']:.2f}x"
    struct_rows = _bank_structural_rows(m, trading_ccy)

    md = f"""# Фундаментальный анализ & оценка банка: {ticker.upper()}

Компания: **{name}** | Цена: **{m['price']:.2f} {trading_ccy}** ({data['price_kind']}, Yahoo Finance, {data['quote_time_label']})

{fx_line}## 1. Экспресс-вердикт и оценка рисков (банковский чеклист)

**{m['verdict']}**

{m['reasoning']}

**Выявленные риски:**

{sins_block}

## 2. Экспресс-анализ процентного дохода и баланса

Показатели в млн. {trading_ccy}. Вместо Revenue/Current Ratio для банков используются NII и Loan-to-Deposit (LTD).

| Показатель | {" | ".join(year_labels)} |
|---|{"---|" * len(year_labels)}
{row("Net Interest Income (NII)", m["net_interest_income"] / 1e6)}
{row("Комиссионный доход", m["commissions_income"] / 1e6)}
{row("Резервы под потери по кредитам (Provision)", m["credit_loss_provision"] / 1e6)}
{row("Чистая прибыль (Net Income)", m["net_income"] / 1e6)}
{row("Акционерный капитал (Shareholders Equity)", m["shareholders_equity"] / 1e6)}

**Loan-to-Deposit Ratio (LTD, последний год): {ltd_txt}** | **Total Debt / Shareholders Equity: {de_txt}**

### Структура кредитного портфеля и депозитной базы (YoY)

| Показатель | {" | ".join(year_labels)} |
|---|{"---|" * len(year_labels)}
{chr(10).join("| " + " | ".join(str(c) for c in r) + " |" for r in struct_rows)}

## 3. Оценка справедливой стоимости: {model_name}

{model_block}

**Справедливая стоимость акции: {m['fair_value_share']:.2f} {trading_ccy}**
Последняя доступная рыночная котировка: {m['price']:.2f} {trading_ccy} ({data['price_kind']}, {data['quote_time_label']}) | Статус: **{m['val_status']}**

## 4. Катализаторы и риски (качественная оценка)

{catalysts_block}

---
У банков отсутствуют Enterprise Value и Net Debt в классическом виде - долговая нагрузка оценивается через Total Debt / Shareholders Equity.
Фундаментальный анализ отвечает на вопрос «что покупать» — точку входа по времени нужно определять в связке с техническим анализом.
"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    md_filename = os.path.join(OUTPUT_DIR, f"{ticker}_fundamental_report_{date_str}.md")
    with open(md_filename, "w") as f:
        f.write(md)
    return md_filename


def build_bank_pdf_report(ticker, retries=5, retry_delay=5, allow_sample=False, catalysts_text=None, required_return=None):
    data = get_company_data(ticker, retries=retries, retry_delay=retry_delay, allow_sample=allow_sample)
    m = compute_bank_metrics(data, required_return=required_return)
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
    year_labels = m["year_labels"]
    verdict = m["verdict"]
    verdict_color = COLORS[m["verdict_color_key"]]
    reasoning = m["reasoning"]
    val_color = COLORS[m["val_color_key"]]

    chart_img_path = generate_nii_chart(year_labels, m["net_interest_income"].values, ticker)

    date_str = datetime.now().strftime("%Y-%m-%d")
    pdf_filename = os.path.join(OUTPUT_DIR, f"{ticker}_fundamental_report_{date_str}.pdf")

    doc = BaseDocTemplate(
        pdf_filename, pagesize=PAGE_SIZE,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN + 15, bottomMargin=MARGIN,
    )
    content_frame = Frame(
        doc.leftMargin, doc.bottomMargin, USABLE_W,
        PAGE_H - doc.topMargin - doc.bottomMargin, id="main",
    )

    def on_later_pages(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(COLORS["accent"])
        canvas.setLineWidth(1.2)
        y_rule = PAGE_H - MARGIN + 4
        canvas.line(MARGIN, y_rule, PAGE_W - MARGIN, y_rule)
        canvas.setFont(FONT_BOLD, 8)
        canvas.setFillColor(COLORS["muted"])
        canvas.drawString(MARGIN, y_rule + 4, f"ФУНДАМЕНТАЛЬНЫЙ АНАЛИЗ БАНКА: {ticker.upper()}")
        canvas.drawRightString(PAGE_W - MARGIN, y_rule + 4, f"{name.upper()}")
        y_footer = MARGIN - 24
        canvas.setStrokeColor(COLORS["bg_alt"])
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, y_footer + 12, PAGE_W - MARGIN, y_footer + 12)
        canvas.setFont(FONT_NAME, 8)
        canvas.setFillColor(COLORS["muted"])
        canvas.drawString(MARGIN, y_footer, "Подготовлено ИИ-помощником фундаментального анализа")
        canvas.drawRightString(PAGE_W - MARGIN, y_footer, f"Страница {doc.page}")
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="content", frames=content_frame, onPage=on_later_pages)])

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("DocTitle", fontName=FONT_BOLD, fontSize=20, textColor=COLORS["heading"], leading=24, spaceAfter=8)
    subtitle_style = ParagraphStyle("DocSub", fontName=FONT_NAME, fontSize=11, textColor=COLORS["muted"], leading=14, spaceAfter=15)
    h1_style = ParagraphStyle("H1", fontName=FONT_BOLD, fontSize=12, textColor=COLORS["heading"], leading=15, spaceBefore=12, spaceAfter=6, keepWithNext=True)
    body_style = ParagraphStyle("Body", fontName=FONT_NAME, fontSize=9.5, textColor=COLORS["body"], leading=13.5, spaceAfter=6, alignment=TA_JUSTIFY)
    verdict_text_style = ParagraphStyle("VerdictText", fontName=FONT_BOLD, fontSize=12, textColor=verdict_color, leading=15, spaceAfter=6)
    callout_text_style = ParagraphStyle("CalloutText", fontName=FONT_NAME, fontSize=9, textColor=COLORS["body"], leading=13)

    story = [
        Paragraph(f"ФУНДАМЕНТАЛЬНЫЙ АНАЛИЗ БАНКА: {ticker.upper()}", title_style),
        Paragraph(
            f"Полный отчет по банку: <b>{name}</b> | Цена: <b>{price:.2f} {trading_ccy}</b> "
            f"({price_kind}, Yahoo Finance, {quote_time_label})",
            subtitle_style,
        ),
        SectionDivider(USABLE_W, COLORS["accent"]),
        Spacer(1, 10),
    ]

    # ── SECTION 1: EXECUTIVE VERDICT ────────────────────────────────────
    story.append(Paragraph("1. Экспресс-вердикт и оценка рисков (банковский чеклист)", h1_style))
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
    if not m["sins"]:
        story.append(CalloutBox(
            "<b>Финансовые риски:</b> Грехов не обнаружено. Показатели банка в безупречной форме.",
            USABLE_W, COLORS, callout_text_style, COLORS["success"],
        ))
    story.append(Spacer(1, 12))

    # ── SECTION 2: NII / BALANCE TRENDS ─────────────────────────────────
    story.append(Paragraph("2. Экспресс-анализ процентного дохода и баланса", h1_style))
    story.append(Paragraph(
        "Вместо Revenue/Current Ratio (неприменимых к банкам) используются Net Interest Income (NII) и "
        f"Loan-to-Deposit Ratio (LTD).{fx_note}",
        body_style,
    ))

    last4 = range(len(year_labels) - 4, len(year_labels))
    fund_headers = [f"Показатель (в млн. {trading_ccy})"] + [year_labels[i] for i in last4]

    def _fmt_last4(series):
        return [
            "N/A" if pd.isna(series.iloc[i]) else f"{series.iloc[i] / 1e6:,.1f}"
            for i in last4
        ]

    fund_rows = [
        ["Net Interest Income (NII)"] + _fmt_last4(m["net_interest_income"]),
        ["Комиссионный доход"] + _fmt_last4(m["commissions_income"]),
        ["Резервы под потери по кредитам"] + _fmt_last4(m["credit_loss_provision"]),
        ["Чистая прибыль (Net Income)"] + _fmt_last4(m["net_income"]),
        ["Акционерный капитал (Shareholders Equity)"] + _fmt_last4(m["shareholders_equity"]),
    ]
    story.append(create_reportlab_table(fund_headers, fund_rows, styles, COLORS, col_widths=[190, 70, 70, 70, 70]))
    story.append(Spacer(1, 8))

    ltd_txt = "N/A" if m["ltd_ratio"] is None else f"{m['ltd_ratio'] * 100:.1f}%"
    de_txt = "N/A" if m["debt_to_equity"] is None else f"{m['debt_to_equity']:.2f}x"
    story.append(Paragraph(
        f"<b>Loan-to-Deposit Ratio (LTD, последний год):</b> {ltd_txt} &nbsp;&nbsp; "
        f"<b>Total Debt / Shareholders Equity:</b> {de_txt} "
        "(у банков нет Enterprise Value/Net Debt в классическом смысле).",
        body_style,
    ))
    story.append(Spacer(1, 8))
    story.append(Image(chart_img_path, width=USABLE_W, height=USABLE_W * 0.4))
    story.append(Spacer(1, 10))

    struct_headers = ["Показатель"] + list(year_labels)
    struct_rows = _bank_structural_rows(m, trading_ccy)
    story.append(Paragraph("<b>Структура кредитного портфеля и депозитной базы (YoY):</b>", body_style))
    story.append(create_reportlab_table(struct_headers, struct_rows, styles, COLORS))
    story.append(Spacer(1, 12))

    # ── SECTION 3: FAIR VALUE (DDM / ROE-P-B) ───────────────────────────
    model_name, model_lines = _bank_valuation_disclosure(m)
    story.append(Paragraph(f"3. Оценка справедливой стоимости: {model_name}", h1_style))
    model_html = "<br/>".join(
        f"• <b>{escape_xml(label)}</b>{': ' + escape_xml(value) if value else ''}"
        for label, value in model_lines
    )
    story.append(CalloutBox(model_html, USABLE_W, COLORS, callout_text_style, COLORS["accent"]))
    story.append(Spacer(1, 8))

    val_banner_text = (
        f"<b>СПРАВЕДЛИВАЯ СТОИМОСТЬ АКЦИИ: {m['fair_value_share']:.2f} {trading_ccy}</b><br/>"
        f"Последняя доступная рыночная котировка: {price:.2f} {trading_ccy} ({price_kind}, {quote_time_label}) "
        f"| Статус: <font color='{val_color.hexval()}'><b>{m['val_status']}</b></font>"
    )
    story.append(CalloutBox(
        val_banner_text, USABLE_W, COLORS,
        ParagraphStyle("ValB", parent=callout_text_style, fontSize=10, leading=14),
        val_color,
    ))
    story.append(Spacer(1, 12))

    # ── SECTION 4: QUALITATIVE CATALYSTS ────────────────────────────────
    story.append(Paragraph("4. Катализаторы и риски (качественная оценка)", h1_style))
    catalysts_html = "<br/>".join(escape_xml(line) for line in catalysts_text.splitlines())
    story.append(CalloutBox(catalysts_html, USABLE_W, COLORS, callout_text_style, COLORS["muted"]))
    story.append(Spacer(1, 12))

    warning_text = (
        "<b>Важное правило методики экспресс-анализа:</b><br/>"
        "Фундаментальный анализ дает нам ответ на вопрос <b>что именно</b> покупать. Однако для определения "
        "наилучшего момента и цены входа, фундаментальный анализ <b>обязательно должен использоваться в связке с "
        "техническим анализом</b>. Не пытайтесь применять их отдельно!<br/>"
        "У банков отсутствуют Enterprise Value и Net Debt в классическом виде - долговая нагрузка оценивается "
        "через Total Debt / Shareholders Equity, а не через WACC-дисконтирование FCF."
    )
    story.append(CalloutBox(warning_text, USABLE_W, COLORS, callout_text_style, COLORS["warning"]))

    doc.build(story)
    print(f"Success! Comprehensive bank report saved to: {pdf_filename}")

    md_filename = build_bank_markdown_report(ticker, data, m, catalysts_text)
    print(f"Success! Markdown bank report saved to: {md_filename}")

    return pdf_filename, md_filename


# ── REIT REPORT RENDERERS (Step 3, spec Section 6.1) ────────────────────
# No "Operating Cash Flow"/DCF sections here - FFO/AFFO/NOI and the NAV
# bridge replace them entirely (spec Section 0: classical DCF is
# meaningless for REITs).
def _reit_nav_bridge_rows(m, trading_ccy):
    """Plain (label, value) pairs for the NAV bridge - shared between the
    PDF and Markdown REIT renderers (spec Section 6.1)."""
    return [
        (f"NOI (последний год)", f"{m['noi'].iloc[-1] / 1e6:,.1f} млн. {trading_ccy}"),
        ("Применённый Cap Rate", f"{m['cap_rate'] * 100:.2f}% ({m['cap_rate_label']})"),
        ("Property Value = NOI / Cap Rate", f"{m['property_value'] / 1e6:,.1f} млн. {trading_ccy}"),
        ("Плюс: Cash", f"{m['cash'].iloc[-1] / 1e6:,.1f} млн. {trading_ccy}"),
        ("Плюс: Receivables", f"{m['receivables'].iloc[-1] / 1e6:,.1f} млн. {trading_ccy}"),
        ("Плюс: Construction in Progress", f"{m['construction_in_progress'].iloc[-1] / 1e6:,.1f} млн. {trading_ccy}"),
        ("Минус: Total Liabilities", f"{m['total_liab'].iloc[-1] / 1e6:,.1f} млн. {trading_ccy}" if not pd.isna(m["total_liab"].iloc[-1]) else "N/A"),
        ("= Net Asset Value (NAV)", f"{m['nav'] / 1e6:,.1f} млн. {trading_ccy}"),
    ]


def _reit_operating_rows(m):
    def fmt(series):
        return ["N/A" if pd.isna(v) else f"{v / 1e6:,.1f}" for v in series]

    return [
        ["FFO (млн.)"] + fmt(m["ffo"]),
        ["AFFO (млн.)"] + fmt(m["affo"]),
        ["NOI (млн.)"] + fmt(m["noi"]),
        ["CapEx (млн.)"] + fmt(m["capex"].abs()),
        ["Dividends Paid (млн.)"] + fmt(m["dividends_paid"]),
    ]


def build_reit_markdown_report(ticker, data, m, catalysts_text=None):
    """REIT twin of build_markdown_report()/build_bank_markdown_report() -
    FFO/AFFO/NOI/Occupancy in the header, NAV valuation bridge instead of
    WACC/DCF, loan/deposit-style operating-performance table."""
    name = data["name"]
    trading_ccy = data.get("trading_currency", "USD")
    financial_ccy = data.get("financial_currency", "USD")
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

    op_rows = _reit_operating_rows(m)
    nav_rows = _reit_nav_bridge_rows(m, trading_ccy)
    nav_block = "\n".join(f"- {label}: {value}" for label, value in nav_rows)
    payout_txt = "N/A (дивиденды не выплачиваются)" if m["affo_payout_ratio"] is None else (
        "∞ (AFFO ≤ 0)" if m["affo_payout_ratio"] == float("inf") else f"{m['affo_payout_ratio'] * 100:.1f}%"
    )
    de_txt = "N/A" if m["debt_to_equity"] is None else f"{m['debt_to_equity']:.2f}x"

    md = f"""# Фундаментальный анализ & оценка REIT: {ticker.upper()}

Компания: **{name}** | Цена: **{m['price']:.2f} {trading_ccy}** ({data['price_kind']}, Yahoo Finance, {data['quote_time_label']})

{fx_line}## 1. Экспресс-вердикт и оценка рисков (чеклист REIT)

**{m['verdict']}**

{m['reasoning']}

**Выявленные риски:**

{sins_block}

## 2. REIT Operating Performance (FFO / AFFO / NOI)

Показатели в млн. {trading_ccy}. Вместо Net Income/операционного кэш-флоу для REIT используются FFO, AFFO и NOI.

| Показатель | {" | ".join(year_labels)} |
|---|{"---|" * len(year_labels)}
{chr(10).join("| " + " | ".join(str(c) for c in r) + " |" for r in op_rows)}

**Occupancy Rate: {m['occupancy_rate'] * 100:.1f}%** | **AFFO Payout Ratio: {payout_txt}** | **Total Debt / Shareholders Equity: {de_txt}**

## 3. NAV Valuation Bridge

{nav_block}

**Справедливая стоимость акции: {m['fair_value_share']:.2f} {trading_ccy}**
Последняя доступная рыночная котировка: {m['price']:.2f} {trading_ccy} ({data['price_kind']}, {data['quote_time_label']}) | Статус: **{m['val_status']}**

## 4. Катализаторы и риски (качественная оценка)

{catalysts_block}

---
Классический DCF неприменим к REIT (искажение денежного потока операциями с недвижимостью) - справедливая стоимость оценивается по методу NAV (Net Asset Value) на базе NOI и отраслевой ставки капитализации (Cap Rate).
Фундаментальный анализ отвечает на вопрос «что покупать» — точку входа по времени нужно определять в связке с техническим анализом.
"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    md_filename = os.path.join(OUTPUT_DIR, f"{ticker}_fundamental_report_{date_str}.md")
    with open(md_filename, "w") as f:
        f.write(md)
    return md_filename


def build_reit_pdf_report(ticker, retries=5, retry_delay=5, allow_sample=False, catalysts_text=None, required_return=None):
    data = get_company_data(ticker, retries=retries, retry_delay=retry_delay, allow_sample=allow_sample)
    m = compute_reit_metrics(data, required_return=required_return)
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
    year_labels = m["year_labels"]
    verdict = m["verdict"]
    verdict_color = COLORS[m["verdict_color_key"]]
    reasoning = m["reasoning"]
    val_color = COLORS[m["val_color_key"]]

    chart_img_path = generate_ffo_chart(year_labels, m["ffo"].values, m["affo"].values, ticker)

    date_str = datetime.now().strftime("%Y-%m-%d")
    pdf_filename = os.path.join(OUTPUT_DIR, f"{ticker}_fundamental_report_{date_str}.pdf")

    doc = BaseDocTemplate(
        pdf_filename, pagesize=PAGE_SIZE,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN + 15, bottomMargin=MARGIN,
    )
    content_frame = Frame(
        doc.leftMargin, doc.bottomMargin, USABLE_W,
        PAGE_H - doc.topMargin - doc.bottomMargin, id="main",
    )

    def on_later_pages(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(COLORS["accent"])
        canvas.setLineWidth(1.2)
        y_rule = PAGE_H - MARGIN + 4
        canvas.line(MARGIN, y_rule, PAGE_W - MARGIN, y_rule)
        canvas.setFont(FONT_BOLD, 8)
        canvas.setFillColor(COLORS["muted"])
        canvas.drawString(MARGIN, y_rule + 4, f"ФУНДАМЕНТАЛЬНЫЙ АНАЛИЗ REIT: {ticker.upper()}")
        canvas.drawRightString(PAGE_W - MARGIN, y_rule + 4, f"{name.upper()}")
        y_footer = MARGIN - 24
        canvas.setStrokeColor(COLORS["bg_alt"])
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, y_footer + 12, PAGE_W - MARGIN, y_footer + 12)
        canvas.setFont(FONT_NAME, 8)
        canvas.setFillColor(COLORS["muted"])
        canvas.drawString(MARGIN, y_footer, "Подготовлено ИИ-помощником фундаментального анализа")
        canvas.drawRightString(PAGE_W - MARGIN, y_footer, f"Страница {doc.page}")
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="content", frames=content_frame, onPage=on_later_pages)])

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("DocTitle", fontName=FONT_BOLD, fontSize=20, textColor=COLORS["heading"], leading=24, spaceAfter=8)
    subtitle_style = ParagraphStyle("DocSub", fontName=FONT_NAME, fontSize=11, textColor=COLORS["muted"], leading=14, spaceAfter=15)
    h1_style = ParagraphStyle("H1", fontName=FONT_BOLD, fontSize=12, textColor=COLORS["heading"], leading=15, spaceBefore=12, spaceAfter=6, keepWithNext=True)
    body_style = ParagraphStyle("Body", fontName=FONT_NAME, fontSize=9.5, textColor=COLORS["body"], leading=13.5, spaceAfter=6, alignment=TA_JUSTIFY)
    verdict_text_style = ParagraphStyle("VerdictText", fontName=FONT_BOLD, fontSize=12, textColor=verdict_color, leading=15, spaceAfter=6)
    callout_text_style = ParagraphStyle("CalloutText", fontName=FONT_NAME, fontSize=9, textColor=COLORS["body"], leading=13)

    story = [
        Paragraph(f"ФУНДАМЕНТАЛЬНЫЙ АНАЛИЗ REIT: {ticker.upper()}", title_style),
        Paragraph(
            f"Полный отчет по REIT: <b>{name}</b> | Цена: <b>{price:.2f} {trading_ccy}</b> "
            f"({price_kind}, Yahoo Finance, {quote_time_label})",
            subtitle_style,
        ),
        SectionDivider(USABLE_W, COLORS["accent"]),
        Spacer(1, 10),
    ]

    # ── SECTION 1: EXECUTIVE VERDICT ────────────────────────────────────
    story.append(Paragraph("1. Экспресс-вердикт и оценка рисков (чеклист REIT)", h1_style))
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
    if not m["sins"]:
        story.append(CalloutBox(
            "<b>Финансовые риски:</b> Грехов не обнаружено. Показатели REIT в безупречной форме.",
            USABLE_W, COLORS, callout_text_style, COLORS["success"],
        ))
    story.append(Spacer(1, 12))

    # ── SECTION 2: FFO/AFFO/NOI TRENDS ──────────────────────────────────
    story.append(Paragraph("2. REIT Operating Performance (FFO / AFFO / NOI)", h1_style))
    story.append(Paragraph(
        "Net Income искажён бумажной амортизацией недвижимости - вместо него используются FFO, AFFO и NOI."
        f"{fx_note}",
        body_style,
    ))

    last4 = range(len(year_labels) - 4, len(year_labels))
    fund_headers = [f"Показатель (в млн. {trading_ccy})"] + [year_labels[i] for i in last4]

    def _fmt_last4(series):
        return ["N/A" if pd.isna(series.iloc[i]) else f"{series.iloc[i] / 1e6:,.1f}" for i in last4]

    fund_rows = [
        ["FFO"] + _fmt_last4(m["ffo"]),
        ["AFFO"] + _fmt_last4(m["affo"]),
        ["NOI"] + _fmt_last4(m["noi"]),
        ["CapEx"] + _fmt_last4(m["capex"].abs()),
        ["Dividends Paid"] + _fmt_last4(m["dividends_paid"]),
    ]
    story.append(create_reportlab_table(fund_headers, fund_rows, styles, COLORS, col_widths=[190, 70, 70, 70, 70]))
    story.append(Spacer(1, 8))

    payout_txt = "N/A (дивиденды не выплачиваются)" if m["affo_payout_ratio"] is None else (
        "∞ (AFFO ≤ 0)" if m["affo_payout_ratio"] == float("inf") else f"{m['affo_payout_ratio'] * 100:.1f}%"
    )
    de_txt = "N/A" if m["debt_to_equity"] is None else f"{m['debt_to_equity']:.2f}x"
    story.append(Paragraph(
        f"<b>Occupancy Rate:</b> {m['occupancy_rate'] * 100:.1f}% &nbsp;&nbsp; "
        f"<b>AFFO Payout Ratio:</b> {payout_txt} &nbsp;&nbsp; "
        f"<b>Total Debt / Shareholders Equity:</b> {de_txt}",
        body_style,
    ))
    story.append(Spacer(1, 8))
    story.append(Image(chart_img_path, width=USABLE_W, height=USABLE_W * 0.4))
    story.append(Spacer(1, 12))

    # ── SECTION 3: NAV VALUATION BRIDGE ─────────────────────────────────
    story.append(Paragraph("3. NAV Valuation Bridge", h1_style))
    nav_rows = _reit_nav_bridge_rows(m, trading_ccy)
    nav_html = "<br/>".join(f"• <b>{escape_xml(label)}:</b> {escape_xml(value)}" for label, value in nav_rows)
    story.append(CalloutBox(nav_html, USABLE_W, COLORS, callout_text_style, COLORS["accent"]))
    story.append(Spacer(1, 8))

    val_banner_text = (
        f"<b>СПРАВЕДЛИВАЯ СТОИМОСТЬ АКЦИИ: {m['fair_value_share']:.2f} {trading_ccy}</b><br/>"
        f"Последняя доступная рыночная котировка: {price:.2f} {trading_ccy} ({price_kind}, {quote_time_label}) "
        f"| Статус: <font color='{val_color.hexval()}'><b>{m['val_status']}</b></font>"
    )
    story.append(CalloutBox(
        val_banner_text, USABLE_W, COLORS,
        ParagraphStyle("ValB", parent=callout_text_style, fontSize=10, leading=14),
        val_color,
    ))
    story.append(Spacer(1, 12))

    # ── SECTION 4: QUALITATIVE CATALYSTS ────────────────────────────────
    story.append(Paragraph("4. Катализаторы и риски (качественная оценка)", h1_style))
    catalysts_html = "<br/>".join(escape_xml(line) for line in catalysts_text.splitlines())
    story.append(CalloutBox(catalysts_html, USABLE_W, COLORS, callout_text_style, COLORS["muted"]))
    story.append(Spacer(1, 12))

    warning_text = (
        "<b>Важное правило методики экспресс-анализа:</b><br/>"
        "Фундаментальный анализ дает нам ответ на вопрос <b>что именно</b> покупать. Однако для определения "
        "наилучшего момента и цены входа, фундаментальный анализ <b>обязательно должен использоваться в связке с "
        "техническим анализом</b>. Не пытайтесь применять их отдельно!<br/>"
        "Классический DCF неприменим к REIT - справедливая стоимость оценивается по методу NAV на базе NOI и "
        "отраслевой ставки капитализации (Cap Rate), а не через WACC-дисконтирование FCF."
    )
    story.append(CalloutBox(warning_text, USABLE_W, COLORS, callout_text_style, COLORS["warning"]))

    doc.build(story)
    print(f"Success! Comprehensive REIT report saved to: {pdf_filename}")

    md_filename = build_reit_markdown_report(ticker, data, m, catalysts_text)
    print(f"Success! Markdown REIT report saved to: {md_filename}")

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
    parser.add_argument(
        "--force", action="store_true",
        help="Принудительно запустить анализ для несовместимых секторов (Финансы/REIT) под ответственность пользователя.",
    )
    parser.add_argument(
        "--required-return", type=required_return_type, default=None,
        help="Персональная требуемая доходность инвестора (0.05-0.25), заменяет CAPM-расчёт Ke.",
    )
    args = parser.parse_args()

    catalysts_text = resolve_catalysts_text(args.catalysts, args.catalysts_file)

    try:
        build_pdf_report(
            args.ticker, retries=args.retries, retry_delay=args.retry_delay,
            allow_sample=args.allow_sample, catalysts_text=catalysts_text, force=args.force,
            required_return=args.required_return,
        )
    except DataUnavailableError as e:
        print(f"FAILED: {e}")
        raise SystemExit(1)
    except UnsupportedSectorError as e:
        print(str(e))
        raise SystemExit(1)
