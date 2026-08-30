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


# Ordinary sin weight tables (MINOR_SIN_WEIGHTS, BUYBACK_BONUS_WEIGHT,
# TECHNICAL_NEGATIVE_EQUITY_WEIGHT, TECHNICAL_LT_INSOLVENCY_WEIGHT) moved
# into the declarative registry in src/fundamental_express/domain/sins.py
# (docs/spec/refactor-tasks.md T11, wired in by T13). MAX_MINOR_SCORE is
# re-exported under its original name since tests/test_verdict_scoring.py
# imports it directly.
from fundamental_express.domain.sins import ORDINARY_MAX_MINOR_SCORE as MAX_MINOR_SCORE  # noqa: E402

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

# Ordinary DCF/DDM, Bank DDM/ROE-P-B, and REIT NAV valuation - moved to
# src/fundamental_express/domain/valuation.py (docs/spec/refactor-tasks.md T12c/T12d/T12e).
from fundamental_express.domain.valuation import (  # noqa: E402
    ordinary_dcf_valuation,
    bank_valuation,
    reit_nav_valuation,
)

# Ordinary sins checklist + registry-driven scoring - moved to
# src/fundamental_express/domain/ordinary.py and domain/sins.py
# (docs/spec/refactor-tasks.md T13).
from fundamental_express.domain.ordinary import check_ordinary_sins  # noqa: E402
from fundamental_express.domain.sins import (  # noqa: E402
    ORDINARY_SIN_REGISTRY,
    ORDINARY_REASONING,
    score,
)
from fundamental_express.domain.metrics import OrdinaryMetrics  # noqa: E402


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

    # ── "Sins" checklist (Ordinary condition checks + registry-driven scoring) ─
    # Moved to src/fundamental_express/domain/ordinary.py (condition checks) and
    # domain/sins.py (scoring) - docs/spec/refactor-tasks.md T13.
    sins, latest_equity, latest_cr = check_ordinary_sins(
        revenue, operating_income, net_income, curr_ratios, equity, fcf,
        gross_margin, operating_margin, net_margin, diluted_shares,
        current_debt, cash, interest_expense, net_debt,
        long_term_assets_adj, long_term_liab,
    )
    scoring = score(sins, ORDINARY_SIN_REGISTRY, ORDINARY_REASONING)
    critical_sins = scoring.critical_sins
    minor_sins = scoring.minor_sins
    minor_score = scoring.minor_score
    verdict = scoring.verdict
    verdict_color_key = scoring.verdict_color_key
    reasoning = scoring.reasoning

    # ── DCF valuation (CAPM WACC, Ordinary v3 DDM auto-switch, sensitivity) ─
    # Moved to src/fundamental_express/domain/valuation.py (docs/spec/refactor-tasks.md T12c).
    valuation, val_extras = ordinary_dcf_valuation(
        fcf, price, shares, beta, required_return, latest_debt, net_debt,
        latest_equity, diluted_shares, cash_dividends_paid, data.get("info"),
    )
    cost_of_equity = valuation.cost_of_equity
    fair_value_share = valuation.fair_value_share
    over_under = valuation.over_under_pct
    val_status = valuation.val_status
    val_color_key = valuation.val_color_key
    valuation_model = valuation.valuation_model
    wacc = val_extras["wacc"]
    after_tax_debt = val_extras["cost_of_debt_after_tax"]
    w_equity = val_extras["equity_weight"]
    w_debt = val_extras["debt_weight"]
    cagr = val_extras["cagr"]
    proj_years = val_extras["proj_years"]
    projected_fcfs = val_extras["projected_fcfs"]
    pv_fcfs = val_extras["pv_fcfs"]
    enterprise_value = val_extras["enterprise_value"]
    equity_value = val_extras["equity_value"]
    sensitivity_headers = val_extras["sensitivity_headers"]
    sensitivity_rows = val_extras["sensitivity_rows"]
    cagr_div = val_extras["cagr_div"]
    dps_last = val_extras["dps_last"]
    debt_to_equity_ratio = val_extras["debt_to_equity_ratio"]

    metrics = OrdinaryMetrics(
        scoring=scoring,
        valuation=valuation,
        year_labels=year_labels,
        revenue=revenue,
        operating_income=operating_income,
        net_income=net_income,
        eps=eps,
        curr_assets=curr_assets,
        curr_liab=curr_liab,
        curr_ratios=curr_ratios,
        equity=equity,
        fcf=fcf,
        net_margin=net_margin,
        wacc=wacc,
        cost_of_debt_after_tax=after_tax_debt,
        equity_weight=w_equity,
        debt_weight=w_debt,
        cagr=cagr,
        proj_years=proj_years,
        projected_fcfs=projected_fcfs,
        pv_fcfs=pv_fcfs,
        enterprise_value=enterprise_value,
        net_debt=net_debt,
        net_debt_source=net_debt_source,
        interest_bearing_debt=latest_debt,
        lease_liabilities=latest_lease_liabilities,
        total_debt_incl_leases=latest_total_debt_incl_leases,
        cash_balance=latest_cash,
        equity_value=equity_value,
        sensitivity_headers=sensitivity_headers,
        sensitivity_rows=sensitivity_rows,
        current_ratio=float(latest_cr),
        net_margin_pct=float(net_margin.iloc[-1]) if not pd.isna(net_margin.iloc[-1]) else None,
        cagr_div=cagr_div,
        dps_last=dps_last,
        debt_to_equity_ratio=debt_to_equity_ratio,
    )
    return metrics


# ── BANK-SPECIFIC ENGINE (Step 2, docs/spec/step2-bank-analyzer-implementation-spec.md) ──
# Commercial banks report interest income/expense, loans and deposits instead
# of revenue/current assets/FCF - the express sins checklist and CAPM/FCF-DCF
# above are mathematically invalid for them (spec Section 1). This is a
# parallel engine, not a variant of compute_metrics(): different checklist
# weights, different valuation models (DDM or ROE/P-B), never called from the
# Ordinary path.
# Bank sin weight table (BANK_MINOR_SIN_WEIGHTS, BANK_BUYBACK_BONUS_WEIGHT)
# moved into the declarative registry in
# src/fundamental_express/domain/sins.py (docs/spec/refactor-tasks.md T11,
# wired in by T14). BANK_MAX_MINOR_SCORE is re-exported under its original
# name since tests/test_bank_analyzer.py imports it directly.
from fundamental_express.domain.sins import (  # noqa: E402
    BANK_MAX_MINOR_SCORE,
    BANK_SIN_REGISTRY,
    BANK_REASONING,
    score,
)
from fundamental_express.domain.bank import check_bank_sins  # noqa: E402
from fundamental_express.domain.metrics import BankMetrics  # noqa: E402


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

    # ── Bank sins checklist (condition checks + registry-driven scoring) ──
    # Moved to src/fundamental_express/domain/bank.py (condition checks) and
    # domain/sins.py (scoring) - docs/spec/refactor-tasks.md T14.
    sins, latest_equity, ltd_ratio, debt_to_equity = check_bank_sins(
        net_interest_income, shareholders_equity, credit_loss_provision,
        diluted_shares, net_loans, total_deposits, cash_and_equiv,
        non_interest_expense, commissions_income, net_income, total_borrowings,
    )
    scoring = score(sins, BANK_SIN_REGISTRY, BANK_REASONING)
    critical_sins = scoring.critical_sins
    minor_sins = scoring.minor_sins
    minor_score = scoring.minor_score
    verdict = scoring.verdict
    verdict_color_key = scoring.verdict_color_key
    reasoning = scoring.reasoning

    # ── Section 5: Fair value (DDM or ROE/P-B) ──────────────────────────
    # Moved to src/fundamental_express/domain/valuation.py (docs/spec/refactor-tasks.md T12d).
    valuation, val_extras = bank_valuation(
        required_return, beta, info, common_dividends_paid, diluted_shares,
        latest_equity, shares, net_income, price,
    )
    cost_of_equity = valuation.cost_of_equity
    fair_value_share = valuation.fair_value_share
    over_under = valuation.over_under_pct
    val_status = valuation.val_status
    val_color_key = valuation.val_color_key
    valuation_model = valuation.valuation_model
    cagr_div = val_extras["cagr_div"]
    dps_last = val_extras["dps_last"]
    bvps = val_extras["bvps"]
    roe = val_extras["roe"]

    metrics = BankMetrics(
        scoring=scoring,
        valuation=valuation,
        year_labels=year_labels,
        interest_income=interest_income,
        interest_expense=interest_expense,
        net_interest_income=net_interest_income,
        commissions_income=commissions_income,
        trading_income=trading_income,
        credit_loss_provision=credit_loss_provision,
        non_interest_expense=non_interest_expense,
        net_income=net_income,
        preferred_dividends=preferred_dividends,
        cash_and_equiv=cash_and_equiv,
        trading_assets=trading_assets,
        htm_securities=htm_securities,
        net_loans=net_loans,
        loan_loss_allowance=loan_loss_allowance,
        total_deposits=total_deposits,
        total_borrowings=total_borrowings,
        shareholders_equity=shareholders_equity,
        diluted_shares=diluted_shares,
        ltd_ratio=ltd_ratio,
        debt_to_equity=debt_to_equity,
        cagr_div=cagr_div,
        dps_last=dps_last,
        bvps=bvps,
        roe=roe,
    )
    return metrics


# ── REIT-SPECIFIC ENGINE (Step 3, docs/spec/step3-reit-analyzer-implementation-spec.md) ──
# REITs' Net Income is artificially depressed by real-estate depreciation
# (a paper charge that doesn't reflect actual cash economics), and standard
# FCF-based DCF is meaningless for a business that's structurally a pass-
# through of rental cash flow - see spec Section 0/2. This is a third
# parallel engine (after Ordinary/Bank): FFO/AFFO/NOI checklist, NAV
# (Net Asset Value) fair value instead of DCF.
# REIT sin weight table (REIT_MINOR_SIN_WEIGHTS, REIT_BUYBACK_BONUS_WEIGHT)
# moved into the declarative registry in
# src/fundamental_express/domain/sins.py (docs/spec/refactor-tasks.md T11,
# wired in by T15). REIT_MAX_MINOR_SCORE is re-exported under its original
# name since tests/test_reit_analyzer.py imports it directly.
from fundamental_express.domain.sins import (  # noqa: E402
    REIT_MAX_MINOR_SCORE,
    REIT_SIN_REGISTRY,
    REIT_REASONING,
    score,
)
from fundamental_express.domain.reit import check_reit_sins  # noqa: E402
from fundamental_express.domain.metrics import ReitMetrics  # noqa: E402


# Moved to src/fundamental_express/domain/valuation.py (docs/spec/refactor-tasks.md T12b).
from fundamental_express.domain.valuation import (  # noqa: E402
    REIT_CAP_RATE_MATRIX,
    REIT_DEFAULT_CAP_RATE,
    REIT_DEFAULT_CAP_RATE_LABEL,
    _reit_cap_rate,
)


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

    # ── REIT sins checklist (condition checks + registry-driven scoring) ──
    # Moved to src/fundamental_express/domain/reit.py (condition checks) and
    # domain/sins.py (scoring) - docs/spec/refactor-tasks.md T15.
    sins, affo_payout_ratio, debt_to_equity = check_reit_sins(
        dividends_paid, affo, occupancy_rate, shareholders_equity,
        diluted_shares, total_debt, noi, capex, ffo,
    )
    scoring = score(sins, REIT_SIN_REGISTRY, REIT_REASONING)
    critical_sins = scoring.critical_sins
    minor_sins = scoring.minor_sins
    minor_score = scoring.minor_score
    verdict = scoring.verdict
    verdict_color_key = scoring.verdict_color_key
    reasoning = scoring.reasoning

    # ── Section 5: NAV fair value ────────────────────────────────────────
    # Moved to src/fundamental_express/domain/valuation.py (docs/spec/refactor-tasks.md T12e).
    valuation, val_extras = reit_nav_valuation(
        info, noi, cash, receivables, construction_in_progress, total_liab,
        shares, price, ffo, diluted_shares, beta,
    )
    fair_value_share = valuation.fair_value_share
    over_under = valuation.over_under_pct
    val_status = valuation.val_status
    val_color_key = valuation.val_color_key
    cap_rate = val_extras["cap_rate"]
    cap_rate_label = val_extras["cap_rate_label"]
    property_value = val_extras["property_value"]
    nav = val_extras["nav"]
    ffo_per_share = val_extras["ffo_per_share"]
    p_ffo = val_extras["p_ffo"]

    metrics = ReitMetrics(
        scoring=scoring,
        valuation=valuation,
        year_labels=year_labels,
        d_and_a=d_and_a,
        gain_on_sale=gain_on_sale,
        capex=capex,
        net_income=net_income,
        rental_revenue=rental_revenue,
        property_opex=property_opex,
        re_taxes=re_taxes,
        construction_in_progress=construction_in_progress,
        receivables=receivables,
        cash=cash,
        total_liab=total_liab,
        total_debt=total_debt,
        shareholders_equity=shareholders_equity,
        diluted_shares=diluted_shares,
        dividends_paid=dividends_paid,
        ffo=ffo,
        affo=affo,
        noi=noi,
        occupancy_rate=occupancy_rate,
        affo_payout_ratio=affo_payout_ratio,
        debt_to_equity=debt_to_equity,
        cap_rate=cap_rate,
        cap_rate_label=cap_rate_label,
        property_value=property_value,
        nav=nav,
        ffo_per_share=ffo_per_share,
        p_ffo=p_ffo,
    )
    return metrics


# ── FORWARD OUTLOOK (Forward P/E, consensus growth, PEG) ────────────────
# Moved to src/fundamental_express/domain/valuation.py (docs/spec/refactor-tasks.md T12a).
from fundamental_express.domain.valuation import (  # noqa: E402
    _EMPTY_FORWARD_OUTLOOK,
    compute_forward_outlook,
    _peg_assessment,
)


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
        f"{m.interest_bearing_debt / 1e9:,.2f} млрд. {trading_ccy}",
    )]
    if not pd.isna(m.lease_liabilities):
        lines.append((
            "Долгосрочные обязательства по аренде (Long-term lease liability, исключены из net debt ниже)",
            f"{m.lease_liabilities / 1e9:,.2f} млрд. {trading_ccy}",
        ))
    if not pd.isna(m.total_debt_incl_leases):
        lines.append((
            "Total Debt (агрегированное поле провайдера данных, включает долг и debt-like "
            "обязательства по его классификации - может не равняться простой сумме строк "
            "выше; справочно, не используется в DCF)",
            f"{m.total_debt_incl_leases / 1e9:,.2f} млрд. {trading_ccy}",
        ))
    lines.append((
        "Денежные средства (Cash and Cash Equivalents)",
        f"{m.cash_balance / 1e9:,.2f} млрд. {trading_ccy}",
    ))
    net_debt_label = (
        "Чистый долг, использован в DCF (поле Net Debt из Yahoo Finance)"
        if m.net_debt_source == "reported"
        else "Чистый долг, использован в DCF (расчёт: Долгосрочный долг − Кэш)"
    )
    lines.append((net_debt_label, f"{m.net_debt / 1e9:,.2f} млрд. {trading_ccy}"))
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
    year_labels = m.year_labels

    def row(label, series, fmt="{:,.1f}"):
        return f"| {label} | " + " | ".join(fmt.format(v) for v in series) + " |"

    if m.scoring.sins:
        sins_parts = []
        if m.scoring.critical_sins:
            sins_parts.append("**Критические:**\n" + "\n".join(f"- {s.message}" for s in m.scoring.critical_sins))
        if m.scoring.minor_sins:
            sins_parts.append(
                f"**Второстепенные (балл {m.scoring.minor_score:.1f} из {m.scoring.max_minor_score:.1f}):**\n"
                + "\n".join(f"- [{s.weight:.1f}] {s.message}" for s in m.scoring.minor_sins)
            )
        sins_block = "\n\n".join(sins_parts)
    else:
        sins_block = "- Грехов не обнаружено."
    debt_block = "\n".join(f"- {label}: {value}" for label, value in _debt_lines(m, trading_ccy))
    sens_header = "| " + " | ".join(m.sensitivity_headers) + " |"
    sens_sep = "|" + "---|" * len(m.sensitivity_headers)
    sens_rows = "\n".join("| " + " | ".join(r) + " |" for r in m.sensitivity_rows)

    peg_color_key, peg_label = _peg_assessment(forward_outlook["peg_ratio"])
    peg_emoji = {"success": "🟢", "warning": "🟡", "danger": "🔴", "muted": "⚪"}[peg_color_key]
    forward_pe_txt = _fmt_or_na(forward_outlook["forward_pe"])
    growth_txt = _fmt_or_na(forward_outlook["growth_pct"], "{:.1f}%")
    peg_txt = _fmt_or_na(forward_outlook["peg_ratio"])
    ke_disclosure = (
        f"Ke = задано инвестором (--required-return) = {m.valuation.cost_of_equity * 100:.2f}%"
        if m.valuation.required_return_used
        else f"Ke = Rf + β×ERP = 4% + {m.valuation.beta:.2f}×5% = {m.valuation.cost_of_equity * 100:.2f}%"
    )

    # Ordinary v3 (Step 4): a dividend-paying company with a distorted
    # capital structure (equity<=0 or D/E>200%) gets valued by DDM instead
    # of DCF - see compute_metrics()'s "Ordinary v3" section. m.valuation.fair_value_share/
    # over_under_pct/val_status already reflect whichever model ran; only the
    # disclosure text below needs to branch, since the DCF-only concepts
    # (WACC, Enterprise Value, sensitivity matrix) don't apply to DDM.
    if m.valuation.valuation_model == "DDM":
        section3_md = f"""## 3. Оценка справедливой стоимости (Модель DDM)

⚠️ **Внимание:** Применена модель дисконтирования дивидендов (DDM) вместо классического DCF - у компании искажена структура капитала (отрицательный или "перегруженный" долгом акционерный капитал) на фоне стабильной истории дивидендных выплат. Классический FCF-DCF в этом случае занижает стоимость (лизинговые/долговые обязательства искажают WACC).

- {ke_disclosure}
- Темп роста дивидендов (CAGR_div, ограничен 2.0%-10.0%): {m.cagr_div * 100:.2f}%
- DPS последнего года (Dividends Paid / Diluted Shares): {m.dps_last:.2f} {trading_ccy}
- Терминальный темп роста (Gordon Growth): 2.5%

**Справедливая стоимость по DDM: {m.valuation.fair_value_share:.2f} {trading_ccy}**
Текущая рыночная цена: {m.valuation.price:.2f} {trading_ccy} ({data['price_kind']}, {data['quote_time_label']}) | Статус: **{m.valuation.val_status}**
"""
    else:
        section3_md = f"""## 3. Модель дисконтирования денежных потоков (DCF)

- Стоимость собственного капитала: {ke_disclosure}
- Стоимость долга после налога: Kd×(1-T) = 4.5%×(1-21%) = {m.cost_of_debt_after_tax * 100:.2f}% (Kd=4.5% и T=21% — фиксированные допущения методики, не специфичны для компании и не эффективная налоговая ставка компании)
- Веса структуры капитала (по рыночной капитализации): E/(D+E) = {m.equity_weight * 100:.1f}%, D/(D+E) = {m.debt_weight * 100:.1f}%
- **WACC:** {m.equity_weight * 100:.1f}%×{m.valuation.cost_of_equity * 100:.2f}% + {m.debt_weight * 100:.1f}%×{m.cost_of_debt_after_tax * 100:.2f}% = **{m.wacc * 100:.2f}%**
- CAGR роста FCF: {m.cagr * 100:.2f}% (историческая, ограничена 2-15%)
- Терминальный темп роста: 2.5%

{debt_block}

> {LEASE_ASSUMPTION_NOTE}

- Enterprise Value: {m.enterprise_value / 1e9:,.2f} млрд. {trading_ccy}
- Equity Value: {m.equity_value / 1e9:,.2f} млрд. {trading_ccy}

**Справедливая стоимость акции: {m.valuation.fair_value_share:.2f} {trading_ccy}**
Последняя доступная рыночная котировка: {m.valuation.price:.2f} {trading_ccy} ({data['price_kind']}, {data['quote_time_label']}) | Статус: **{m.valuation.val_status}**

### Матрица чувствительности (г — рост явного 5-летнего прогноза FCF; терминальный рост фиксирован на 2.5% и используется только в формуле Гордона — условие WACC > g не требуется для этой матрицы)

{sens_header}
{sens_sep}
{sens_rows}
"""

    md = f"""{sector_warning_line}# Фундаментальный анализ & оценка DCF: {ticker.upper()}

Компания: **{name}** | Цена: **{m.valuation.price:.2f} {trading_ccy}** ({data['price_kind']}, Yahoo Finance, {data['quote_time_label']})

{fx_line}## 1. Экспресс-вердикт и оценка рисков

**{m.scoring.verdict}**

{m.scoring.reasoning}

**Выявленные риски:**

{sins_block}

## 2. Экспресс-анализ финансовых результатов и баланса

Показатели в млн. {trading_ccy}.

| Показатель | {" | ".join(year_labels)} |
|---|{"---|" * len(year_labels)}
{row("Выручка (Revenue)", [v / 1e6 for v in m.revenue])}
{row("Операционная прибыль", [v / 1e6 for v in m.operating_income])}
{row("Чистая прибыль (Net Income)", [v / 1e6 for v in m.net_income])}
{row("Разводненная EPS, USD", list(m.eps), fmt="{:.2f}")}
{row("Оборотные активы", [v / 1e6 for v in m.curr_assets])}
{row("Краткосрочные обязательства", [v / 1e6 for v in m.curr_liab])}
{row("Current Ratio", list(m.curr_ratios), fmt="{:.2f}")}
{row("Акционерный капитал", [v / 1e6 for v in m.equity])}
{row("Free Cash Flow", [v / 1e6 for v in m.fcf])}

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
    forward_outlook = compute_forward_outlook(data.get("info", {}), m.valuation.price, m.eps, m.cagr)
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
    price = m.valuation.price
    beta = m.valuation.beta
    year_labels = m.year_labels
    revenue = m.revenue
    operating_income = m.operating_income
    net_income = m.net_income
    eps = m.eps
    curr_assets = m.curr_assets
    curr_liab = m.curr_liab
    curr_ratios = m.curr_ratios
    equity = m.equity
    fcf = m.fcf
    sins = m.scoring.sins
    verdict = m.scoring.verdict
    verdict_color = COLORS[m.scoring.verdict_color_key]
    reasoning = m.scoring.reasoning
    wacc = m.wacc
    cagr = m.cagr
    proj_years = m.proj_years
    projected_fcfs = m.projected_fcfs
    pv_fcfs = m.pv_fcfs
    enterprise_value = m.enterprise_value
    net_debt = m.net_debt
    debt_lines = _debt_lines(m, trading_ccy)
    cost_of_equity = m.valuation.cost_of_equity
    cost_of_debt_after_tax = m.cost_of_debt_after_tax
    equity_weight = m.equity_weight
    debt_weight = m.debt_weight
    equity_value = m.equity_value
    fair_value_share = m.valuation.fair_value_share
    val_status = m.valuation.val_status
    val_color = COLORS[m.valuation.val_color_key]
    sensitivity_headers = m.sensitivity_headers
    sensitivity_rows = m.sensitivity_rows

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

    if m.scoring.critical_sins:
        crit_text = (
            "<b>Критические риски (любой из них — основание для ПРОПУСТИТЬ):</b><br/>"
            + "<br/>".join(f"• {escape_xml(s.message)}" for s in m.scoring.critical_sins)
        )
        story.append(CalloutBox(crit_text, USABLE_W, COLORS, callout_text_style, COLORS["danger"]))
        story.append(Spacer(1, 6))
    if m.scoring.minor_sins:
        minor_text = (
            f"<b>Второстепенные риски (балл {m.scoring.minor_score:.1f} из {m.scoring.max_minor_score:.1f}):</b><br/>"
            + "<br/>".join(f"• [{s.weight:.1f}] {escape_xml(s.message)}" for s in m.scoring.minor_sins)
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
    # "Ordinary v3" section for why/when DDM replaces DCF here -
    # m.valuation.fair_value_share/val_status already reflect whichever model ran.
    if m.valuation.valuation_model == "DDM":
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
            if m.valuation.required_return_used
            else f"Ke = Rf + β×ERP = 4% + {beta:.2f}×5% = {cost_of_equity * 100:.2f}%"
        )
        ddm_info_text = (
            f"• <b>Стоимость собственного капитала:</b> {ke_disclosure}<br/>"
            f"• <b>Темп роста дивидендов (CAGR_div, ограничен 2.0%-10.0%):</b> {m.cagr_div * 100:.2f}%<br/>"
            f"• <b>DPS последнего года (Dividends Paid / Diluted Shares):</b> {m.dps_last:.2f} {trading_ccy}<br/>"
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
            if m.valuation.required_return_used
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
        f"Ke = задано инвестором (--required-return) = {m.valuation.cost_of_equity * 100:.2f}%"
        if m.valuation.required_return_used
        else f"Ke = Rf + β×ERP = 4% + {m.valuation.beta:.2f}×5% = {m.valuation.cost_of_equity * 100:.2f}%"
    )
    if m.valuation.valuation_model == "DDM":
        return "Модель дисконтирования дивидендов (DDM)", [
            (ke_line, ""),
            ("Темп роста дивидендов (CAGR_div, ограничен 1.0%-8.0%)", f"{m.cagr_div * 100:.2f}%"),
            ("DPS последнего года (Common Dividends Paid / Diluted Shares)", f"{m.dps_last:.2f} USD"),
            ("Терминальный темп роста (Gordon Growth)", "2.5%"),
        ]
    return "Модель рентабельности капитала (ROE / P/B)", [
        (ke_line, ""),
        ("Балансовая стоимость на акцию (BVPS)", f"{m.bvps:.2f} USD"),
        ("Рентабельность капитала (ROE)", f"{m.roe * 100:.2f}%"),
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
        ["Net Loans (млн.)"] + fmt(m.net_loans),
        ["Allowance for Credit Losses (млн.)"] + fmt(m.loan_loss_allowance),
        ["Total Deposits (млн.)"] + fmt(m.total_deposits),
        ["LTD Ratio"] + [
            "N/A" if pd.isna(l) or pd.isna(d) or d == 0 else f"{(l / d) * 100:.1f}%"
            for l, d in zip(m.net_loans, m.total_deposits)
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
    year_labels = m.year_labels

    def row(label, series, fmt="{:,.1f}"):
        return f"| {label} | " + " | ".join(
            "N/A" if pd.isna(v) else fmt.format(v) for v in series
        ) + " |"

    if m.scoring.sins:
        sins_parts = []
        if m.scoring.critical_sins:
            sins_parts.append("**Критические:**\n" + "\n".join(f"- {s.message}" for s in m.scoring.critical_sins))
        if m.scoring.minor_sins:
            sins_parts.append(
                f"**Второстепенные (балл {m.scoring.minor_score:.1f} из {m.scoring.max_minor_score:.1f}):**\n"
                + "\n".join(f"- [{s.weight:.1f}] {s.message}" for s in m.scoring.minor_sins)
            )
        sins_block = "\n\n".join(sins_parts)
    else:
        sins_block = "- Грехов не обнаружено."

    model_name, model_lines = _bank_valuation_disclosure(m)
    model_block = "\n".join(f"- {label}{': ' + value if value else ''}" for label, value in model_lines)
    ltd_txt = "N/A" if m.ltd_ratio is None else f"{m.ltd_ratio * 100:.1f}%"
    de_txt = "N/A" if m.debt_to_equity is None else f"{m.debt_to_equity:.2f}x"
    struct_rows = _bank_structural_rows(m, trading_ccy)

    md = f"""# Фундаментальный анализ & оценка банка: {ticker.upper()}

Компания: **{name}** | Цена: **{m.valuation.price:.2f} {trading_ccy}** ({data['price_kind']}, Yahoo Finance, {data['quote_time_label']})

{fx_line}## 1. Экспресс-вердикт и оценка рисков (банковский чеклист)

**{m.scoring.verdict}**

{m.scoring.reasoning}

**Выявленные риски:**

{sins_block}

## 2. Экспресс-анализ процентного дохода и баланса

Показатели в млн. {trading_ccy}. Вместо Revenue/Current Ratio для банков используются NII и Loan-to-Deposit (LTD).

| Показатель | {" | ".join(year_labels)} |
|---|{"---|" * len(year_labels)}
{row("Net Interest Income (NII)", m.net_interest_income / 1e6)}
{row("Комиссионный доход", m.commissions_income / 1e6)}
{row("Резервы под потери по кредитам (Provision)", m.credit_loss_provision / 1e6)}
{row("Чистая прибыль (Net Income)", m.net_income / 1e6)}
{row("Акционерный капитал (Shareholders Equity)", m.shareholders_equity / 1e6)}

**Loan-to-Deposit Ratio (LTD, последний год): {ltd_txt}** | **Total Debt / Shareholders Equity: {de_txt}**

### Структура кредитного портфеля и депозитной базы (YoY)

| Показатель | {" | ".join(year_labels)} |
|---|{"---|" * len(year_labels)}
{chr(10).join("| " + " | ".join(str(c) for c in r) + " |" for r in struct_rows)}

## 3. Оценка справедливой стоимости: {model_name}

{model_block}

**Справедливая стоимость акции: {m.valuation.fair_value_share:.2f} {trading_ccy}**
Последняя доступная рыночная котировка: {m.valuation.price:.2f} {trading_ccy} ({data['price_kind']}, {data['quote_time_label']}) | Статус: **{m.valuation.val_status}**

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
    price = m.valuation.price
    year_labels = m.year_labels
    verdict = m.scoring.verdict
    verdict_color = COLORS[m.scoring.verdict_color_key]
    reasoning = m.scoring.reasoning
    val_color = COLORS[m.valuation.val_color_key]

    chart_img_path = generate_nii_chart(year_labels, m.net_interest_income.values, ticker)

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

    if m.scoring.critical_sins:
        crit_text = (
            "<b>Критические риски (любой из них — основание для ПРОПУСТИТЬ):</b><br/>"
            + "<br/>".join(f"• {escape_xml(s.message)}" for s in m.scoring.critical_sins)
        )
        story.append(CalloutBox(crit_text, USABLE_W, COLORS, callout_text_style, COLORS["danger"]))
        story.append(Spacer(1, 6))
    if m.scoring.minor_sins:
        minor_text = (
            f"<b>Второстепенные риски (балл {m.scoring.minor_score:.1f} из {m.scoring.max_minor_score:.1f}):</b><br/>"
            + "<br/>".join(f"• [{s.weight:.1f}] {escape_xml(s.message)}" for s in m.scoring.minor_sins)
        )
        story.append(CalloutBox(minor_text, USABLE_W, COLORS, callout_text_style, COLORS["warning"]))
    if not m.scoring.sins:
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
        ["Net Interest Income (NII)"] + _fmt_last4(m.net_interest_income),
        ["Комиссионный доход"] + _fmt_last4(m.commissions_income),
        ["Резервы под потери по кредитам"] + _fmt_last4(m.credit_loss_provision),
        ["Чистая прибыль (Net Income)"] + _fmt_last4(m.net_income),
        ["Акционерный капитал (Shareholders Equity)"] + _fmt_last4(m.shareholders_equity),
    ]
    story.append(create_reportlab_table(fund_headers, fund_rows, styles, COLORS, col_widths=[190, 70, 70, 70, 70]))
    story.append(Spacer(1, 8))

    ltd_txt = "N/A" if m.ltd_ratio is None else f"{m.ltd_ratio * 100:.1f}%"
    de_txt = "N/A" if m.debt_to_equity is None else f"{m.debt_to_equity:.2f}x"
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
        f"<b>СПРАВЕДЛИВАЯ СТОИМОСТЬ АКЦИИ: {m.valuation.fair_value_share:.2f} {trading_ccy}</b><br/>"
        f"Последняя доступная рыночная котировка: {price:.2f} {trading_ccy} ({price_kind}, {quote_time_label}) "
        f"| Статус: <font color='{val_color.hexval()}'><b>{m.valuation.val_status}</b></font>"
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
        (f"NOI (последний год)", f"{m.noi.iloc[-1] / 1e6:,.1f} млн. {trading_ccy}"),
        ("Применённый Cap Rate", f"{m.cap_rate * 100:.2f}% ({m.cap_rate_label})"),
        ("Property Value = NOI / Cap Rate", f"{m.property_value / 1e6:,.1f} млн. {trading_ccy}"),
        ("Плюс: Cash", f"{m.cash.iloc[-1] / 1e6:,.1f} млн. {trading_ccy}"),
        ("Плюс: Receivables", f"{m.receivables.iloc[-1] / 1e6:,.1f} млн. {trading_ccy}"),
        ("Плюс: Construction in Progress", f"{m.construction_in_progress.iloc[-1] / 1e6:,.1f} млн. {trading_ccy}"),
        ("Минус: Total Liabilities", f"{m.total_liab.iloc[-1] / 1e6:,.1f} млн. {trading_ccy}" if not pd.isna(m.total_liab.iloc[-1]) else "N/A"),
        ("= Net Asset Value (NAV)", f"{m.nav / 1e6:,.1f} млн. {trading_ccy}"),
    ]


def _reit_operating_rows(m):
    def fmt(series):
        return ["N/A" if pd.isna(v) else f"{v / 1e6:,.1f}" for v in series]

    return [
        ["FFO (млн.)"] + fmt(m.ffo),
        ["AFFO (млн.)"] + fmt(m.affo),
        ["NOI (млн.)"] + fmt(m.noi),
        ["CapEx (млн.)"] + fmt(m.capex.abs()),
        ["Dividends Paid (млн.)"] + fmt(m.dividends_paid),
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
    year_labels = m.year_labels

    if m.scoring.sins:
        sins_parts = []
        if m.scoring.critical_sins:
            sins_parts.append("**Критические:**\n" + "\n".join(f"- {s.message}" for s in m.scoring.critical_sins))
        if m.scoring.minor_sins:
            sins_parts.append(
                f"**Второстепенные (балл {m.scoring.minor_score:.1f} из {m.scoring.max_minor_score:.1f}):**\n"
                + "\n".join(f"- [{s.weight:.1f}] {s.message}" for s in m.scoring.minor_sins)
            )
        sins_block = "\n\n".join(sins_parts)
    else:
        sins_block = "- Грехов не обнаружено."

    op_rows = _reit_operating_rows(m)
    nav_rows = _reit_nav_bridge_rows(m, trading_ccy)
    nav_block = "\n".join(f"- {label}: {value}" for label, value in nav_rows)
    payout_txt = "N/A (дивиденды не выплачиваются)" if m.affo_payout_ratio is None else (
        "∞ (AFFO ≤ 0)" if m.affo_payout_ratio == float("inf") else f"{m.affo_payout_ratio * 100:.1f}%"
    )
    de_txt = "N/A" if m.debt_to_equity is None else f"{m.debt_to_equity:.2f}x"

    md = f"""# Фундаментальный анализ & оценка REIT: {ticker.upper()}

Компания: **{name}** | Цена: **{m.valuation.price:.2f} {trading_ccy}** ({data['price_kind']}, Yahoo Finance, {data['quote_time_label']})

{fx_line}## 1. Экспресс-вердикт и оценка рисков (чеклист REIT)

**{m.scoring.verdict}**

{m.scoring.reasoning}

**Выявленные риски:**

{sins_block}

## 2. REIT Operating Performance (FFO / AFFO / NOI)

Показатели в млн. {trading_ccy}. Вместо Net Income/операционного кэш-флоу для REIT используются FFO, AFFO и NOI.

| Показатель | {" | ".join(year_labels)} |
|---|{"---|" * len(year_labels)}
{chr(10).join("| " + " | ".join(str(c) for c in r) + " |" for r in op_rows)}

**Occupancy Rate: {m.occupancy_rate * 100:.1f}%** | **AFFO Payout Ratio: {payout_txt}** | **Total Debt / Shareholders Equity: {de_txt}**

## 3. NAV Valuation Bridge

{nav_block}

**Справедливая стоимость акции: {m.valuation.fair_value_share:.2f} {trading_ccy}**
Последняя доступная рыночная котировка: {m.valuation.price:.2f} {trading_ccy} ({data['price_kind']}, {data['quote_time_label']}) | Статус: **{m.valuation.val_status}**

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
    price = m.valuation.price
    year_labels = m.year_labels
    verdict = m.scoring.verdict
    verdict_color = COLORS[m.scoring.verdict_color_key]
    reasoning = m.scoring.reasoning
    val_color = COLORS[m.valuation.val_color_key]

    chart_img_path = generate_ffo_chart(year_labels, m.ffo.values, m.affo.values, ticker)

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

    if m.scoring.critical_sins:
        crit_text = (
            "<b>Критические риски (любой из них — основание для ПРОПУСТИТЬ):</b><br/>"
            + "<br/>".join(f"• {escape_xml(s.message)}" for s in m.scoring.critical_sins)
        )
        story.append(CalloutBox(crit_text, USABLE_W, COLORS, callout_text_style, COLORS["danger"]))
        story.append(Spacer(1, 6))
    if m.scoring.minor_sins:
        minor_text = (
            f"<b>Второстепенные риски (балл {m.scoring.minor_score:.1f} из {m.scoring.max_minor_score:.1f}):</b><br/>"
            + "<br/>".join(f"• [{s.weight:.1f}] {escape_xml(s.message)}" for s in m.scoring.minor_sins)
        )
        story.append(CalloutBox(minor_text, USABLE_W, COLORS, callout_text_style, COLORS["warning"]))
    if not m.scoring.sins:
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
        ["FFO"] + _fmt_last4(m.ffo),
        ["AFFO"] + _fmt_last4(m.affo),
        ["NOI"] + _fmt_last4(m.noi),
        ["CapEx"] + _fmt_last4(m.capex.abs()),
        ["Dividends Paid"] + _fmt_last4(m.dividends_paid),
    ]
    story.append(create_reportlab_table(fund_headers, fund_rows, styles, COLORS, col_widths=[190, 70, 70, 70, 70]))
    story.append(Spacer(1, 8))

    payout_txt = "N/A (дивиденды не выплачиваются)" if m.affo_payout_ratio is None else (
        "∞ (AFFO ≤ 0)" if m.affo_payout_ratio == float("inf") else f"{m.affo_payout_ratio * 100:.1f}%"
    )
    de_txt = "N/A" if m.debt_to_equity is None else f"{m.debt_to_equity:.2f}x"
    story.append(Paragraph(
        f"<b>Occupancy Rate:</b> {m.occupancy_rate * 100:.1f}% &nbsp;&nbsp; "
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
        f"<b>СПРАВЕДЛИВАЯ СТОИМОСТЬ АКЦИИ: {m.valuation.fair_value_share:.2f} {trading_ccy}</b><br/>"
        f"Последняя доступная рыночная котировка: {price:.2f} {trading_ccy} ({price_kind}, {quote_time_label}) "
        f"| Статус: <font color='{val_color.hexval()}'><b>{m.valuation.val_status}</b></font>"
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
