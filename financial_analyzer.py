import dataclasses
import os
import sys
from datetime import datetime

# Resolve workspace root relative to this script file, purely to bootstrap
# sys.path below before fundamental_express is importable - the canonical
# SCRIPT_DIR/SCRATCH_DIR/OUTPUT_DIR now live in
# fundamental_express.cli.paths (docs/spec/refactor-tasks.md T22) and are
# re-imported a few lines down once that import becomes possible.
_BOOTSTRAP_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Package-under-migration lives in src/ (docs/spec/refactor-architecture-spec.md)
# and isn't installed - add it to sys.path so `python financial_analyzer.py`
# keeps working unchanged from any working directory.
sys.path.insert(0, os.path.join(_BOOTSTRAP_SCRIPT_DIR, "src"))

import pandas as pd

# Moved to src/fundamental_express/cli/paths.py (docs/spec/refactor-tasks.md
# T22). SCRIPT_DIR/SCRATCH_DIR are not otherwise used in this file anymore,
# but stay re-exported under their original names since nothing forbids an
# external caller from having imported them from here before T22.
from fundamental_express.cli.paths import SCRIPT_DIR, SCRATCH_DIR, OUTPUT_DIR  # noqa: E402

# The express "sins" checklist in compute_metrics() is a two-tier model
# (see docs/spec/technical-implementation-spec.md Section 1):
#   - CRITICAL sins (fcf_negative, cr_below_1, lt_insolvency, equity_negative):
#     any single hit forces verdict = SKIP, regardless of everything else.
#   - MINOR sins: weighted 1.0/0.5/0.3 by how directly they reflect real
#     operating/cash health vs how noisy/paper-driven the metric is. Weights
#     sum to MAX_MINOR_SCORE and decide BUY/WATCH/SKIP when no critical sin
#     fired.
# `Sin` itself moved to src/fundamental_express/domain/sins.py in T11 and is
# constructed there (via fire()) by every domain/{ordinary,bank,reit}.py
# condition-check module (T13/T14/T15) - financial_analyzer.py never
# constructs one directly anymore, so it's not re-exported here.

# Ordinary sin weight tables (MINOR_SIN_WEIGHTS, BUYBACK_BONUS_WEIGHT,
# TECHNICAL_NEGATIVE_EQUITY_WEIGHT, TECHNICAL_LT_INSOLVENCY_WEIGHT) moved
# into the declarative registry in src/fundamental_express/domain/sins.py
# (docs/spec/refactor-tasks.md T11, wired in by T13). MAX_MINOR_SCORE is
# re-exported under its original name since tests/test_verdict_scoring.py
# imports it directly.
from fundamental_express.domain.sins import ORDINARY_MAX_MINOR_SCORE as MAX_MINOR_SCORE  # noqa: E402

# ── VISUAL THEME (colors, fonts, page geometry) ─────────────────────────
# Moved to src/fundamental_express/reporting/theme.py (docs/spec/refactor-tasks.md T02).
# escape_xml/_fmt_or_na are not re-exported here - their only callers moved
# into reporting/pdf.py and the reporting/sections_*.py modules in T20.
from fundamental_express.reporting.theme import (  # noqa: E402
    COLORS,
    FONT_NAME,
    FONT_BOLD,
    PAGE_SIZE,
    MARGIN,
    PAGE_W,
    PAGE_H,
    USABLE_W,
)


# ── FINANCIAL STATEMENT PARSING (row locator, year alignment) ──────────
# Moved to src/fundamental_express/data/parsing.py (docs/spec/refactor-tasks.md T06).
from fundamental_express.data.parsing import find_row, _align_statement_years  # noqa: E402


# ── ERRORS ───────────────────────────────────────────────────────────────
# Moved to src/fundamental_express/data/errors.py (docs/spec/refactor-tasks.md T07).
from fundamental_express.data.errors import DataUnavailableError, UnsupportedSectorError  # noqa: E402


# Moved to src/fundamental_express/domain/routing.py (docs/spec/refactor-tasks.md T08).
from fundamental_express.domain.routing import check_sector_suitability, _is_lease_heavy  # noqa: E402


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


# ── PDF FLOWABLES (section divider, callout box) ────────────────────────
# Moved to src/fundamental_express/reporting/flowables.py (docs/spec/refactor-tasks.md T03).
# SectorWarningBanner is not re-exported here - its only caller moved into
# reporting/pdf.py in T20.
from fundamental_express.reporting.flowables import SectionDivider, CalloutBox  # noqa: E402


# ── SHARED PDF TABLE BUILDER ─────────────────────────────────────────────
# Moved to src/fundamental_express/reporting/tables.py (docs/spec/refactor-tasks.md T04).
from fundamental_express.reporting.tables import create_reportlab_table  # noqa: E402

# Chart generators (FCF/NII/FFO, src/fundamental_express/reporting/charts.py,
# T05) are not re-exported here - every caller moved into the
# reporting/sections_*.py modules in T20.

# Ordinary DCF/DDM, Bank DDM/ROE-P-B, and REIT NAV valuation - moved to
# src/fundamental_express/domain/valuation.py (docs/spec/refactor-tasks.md T12c/T12d/T12e).
from fundamental_express.domain.valuation import (  # noqa: E402
    ordinary_dcf_valuation,
    bank_valuation,
    reit_nav_valuation,
)
from fundamental_express.domain.graham import graham_number, eps_for_graham  # noqa: E402

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


def _nonrecurring_note(year_labels, raw, normalized, source_row):
    """V03 (docs/spec/issues/V03-normalize-nonrecurring-items.md): a
    human-readable disclosure line naming every year where a non-recurring
    item (from yfinance's own "Normalized Income" row) was stripped out of
    net income before the declining-earnings sin check - so a reviewer can
    see which years were touched and by how much, not just trust a swapped
    number. Returns None when the source row wasn't found or covered no
    year with a real (non-negligible) adjustment - the common case.
    """
    adjustments = []
    for i, year in enumerate(year_labels):
        if pd.isna(source_row.iloc[i]):
            continue
        delta = raw.iloc[i] - normalized.iloc[i]
        if abs(delta) > 1e6:  # ignore sub-$1M rounding noise
            adjustments.append((year, delta))
    if not adjustments:
        return None
    parts = [
        f"{year} ({'−' if delta > 0 else '+'}{abs(delta) / 1e6:,.0f} млн)"
        for year, delta in adjustments
    ]
    return (
        "Скорректировано (для расчёта тренда прибыли): исключены разовые статьи "
        "(Normalized Income vs. reported Net Income) за " + ", ".join(parts) + "."
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
    # V03: yfinance's own "Normalized Income" row (nets out impairments,
    # gains/losses on sale, restructuring, and other one-off items it
    # identifies) - used only to normalize the net_income_declining sin
    # input below, per-year. NaN (row missing, or that year not covered)
    # falls back to the raw net_income for that specific year via
    # .fillna() further down, once both are FX-converted.
    normalized_income = find_row(df_fin, ["normalized income"], default_val=float("nan"))
    eps = find_row(df_fin, ["eps", "diluted eps", "basic eps"])

    revenue_cost = find_row(df_fin, ["cost of revenue"], default_val=float("nan"))

    curr_assets = find_row(df_bal, ["total current assets", "current assets"])
    curr_liab = find_row(df_bal, ["total current liabilities", "current liabilities"])
    total_assets = find_row(df_bal, ["total assets"])
    total_liab = find_row(df_bal, ["total liabilities"], default_val=float("nan"))
    goodwill = find_row(df_bal, ["goodwill"])
    # V01: separate "Other Intangible Assets" row, when yfinance exposes one
    # distinctly from Goodwill - feeds tangible_equity below alongside it.
    other_intangibles = find_row(df_bal, ["other intangible assets"], default_val=0.0)
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
        normalized_income = normalized_income * fx_rate
        curr_assets = curr_assets * fx_rate
        curr_liab = curr_liab * fx_rate
        total_assets = total_assets * fx_rate
        total_liab = total_liab * fx_rate
        goodwill = goodwill * fx_rate
        other_intangibles = other_intangibles * fx_rate
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

    # V01: tangible equity - same goodwill exclusion as long_term_assets_adj
    # above, now also feeding the DCF's D/E distress trigger (see
    # docs/spec/issues/V01-tangible-equity-distress-triggers.md).
    tangible_equity = equity - goodwill - other_intangibles

    # V03: net_income_normalized feeds only the net_income_declining sin
    # below - the raw, reported net_income in the fundamentals table and
    # net_margin above is untouched (see
    # docs/spec/issues/V03-normalize-nonrecurring-items.md).
    net_income_normalized = normalized_income.fillna(net_income)
    nonrecurring_note = _nonrecurring_note(year_labels, net_income, net_income_normalized, normalized_income)

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

    # V04: lease-inclusive net debt, always computed as a secondary figure
    # (headline for lease-heavy sectors, decided further below once
    # Enterprise Value is available) - see
    # docs/spec/issues/V04-lease-adjusted-net-debt.md.
    debt_already_lease_inclusive = interest_bearing_debt.isna().all()
    if net_debt_source != "computed":
        # Yahoo's own reported Net Debt methodology re: leases is
        # undocumented - don't guess, show N/A rather than silently
        # double-count or omit (see FU-08 for the related, pre-existing
        # inconsistency this task does not fix).
        net_debt_incl_leases = None
    elif debt_already_lease_inclusive:
        # `debt` already fell back to total_debt_incl_leases (no separate
        # Long Term Debt row for this ticker) - net_debt is already
        # lease-inclusive, adding lease_liabilities again would double-count.
        net_debt_incl_leases = net_debt
    elif not pd.isna(latest_lease_liabilities):
        net_debt_incl_leases = net_debt + latest_lease_liabilities
    elif not pd.isna(latest_total_debt_incl_leases):
        net_debt_incl_leases = net_debt + (latest_total_debt_incl_leases - latest_debt)
    else:
        net_debt_incl_leases = None

    # ── "Sins" checklist (Ordinary condition checks + registry-driven scoring) ─
    # Moved to src/fundamental_express/domain/ordinary.py (condition checks) and
    # domain/sins.py (scoring) - docs/spec/refactor-tasks.md T13.
    sins, latest_equity, latest_cr = check_ordinary_sins(
        revenue, operating_income, net_income_normalized, curr_ratios, equity, fcf,
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
    latest_tangible_equity = tangible_equity.iloc[-1] if len(tangible_equity) else float("nan")
    latest_interest_expense = interest_expense.iloc[-1] if len(interest_expense) else float("nan")

    # V10 (docs/spec/issues/V10-graham-number-reproducible.md) - purely
    # informational, never feeds sins/verdict/DCF. tangible_bvps reuses
    # V01's tangible_equity rather than raw equity (goodwill-inflated
    # raw BVPS overstates Graham's "ceiling" price).
    graham_eps, graham_eps_label = eps_for_graham(data.get("info"), eps.iloc[-1] if len(eps) else None)
    graham_tangible_bvps = (
        latest_tangible_equity / shares if shares > 0 and not pd.isna(latest_tangible_equity) else None
    )
    graham_value = graham_number(graham_eps, graham_tangible_bvps)
    valuation, val_extras = ordinary_dcf_valuation(
        fcf, price, shares, beta, required_return, latest_debt, net_debt,
        latest_equity, diluted_shares, cash_dividends_paid, data.get("info"),
        tangible_equity=latest_tangible_equity, interest_expense=latest_interest_expense,
        beta_is_fallback=data.get("beta_is_fallback", False),
    )
    cost_of_equity = valuation.cost_of_equity
    fair_value_share = valuation.fair_value_share
    over_under = valuation.over_under_pct
    val_status = valuation.val_status
    val_color_key = valuation.val_color_key
    valuation_model = valuation.valuation_model
    wacc = val_extras["wacc"]
    after_tax_debt = val_extras["cost_of_debt_after_tax"]
    cost_of_debt = val_extras["cost_of_debt"]
    cost_of_debt_is_implied = val_extras["cost_of_debt_is_implied"]
    terminal_g = val_extras["terminal_g"]
    terminal_g_label = val_extras["terminal_g_label"]
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

    # V04: lease-inclusive fair value - EV doesn't depend on net_debt (only
    # equity_value = EV - net_debt does), so this is a cheap second
    # subtraction, not a second DCF run. Only meaningful on the FCF-DCF
    # path (valuation_model == "DCF") - DDM discounts dividends directly
    # and has no EV/net_debt concept to re-net. Always computed and always
    # shown as a secondary figure in the report; only promoted to headline
    # for a lease-heavy sector (see docs/spec/issues/V04-lease-adjusted-net-debt.md).
    fair_value_share_incl_leases = None
    if valuation_model == "DCF" and net_debt_incl_leases is not None and shares > 0:
        equity_value_incl_leases = enterprise_value - net_debt_incl_leases
        fair_value_share_incl_leases = equity_value_incl_leases / shares
    # Saved before any headline override below, so the report can always
    # show whichever of the two (excl/incl leases) is NOT the headline.
    fair_value_share_excl_leases = fair_value_share if valuation_model == "DCF" else None

    lease_heavy_sector = _is_lease_heavy(data.get("info") or {})
    if lease_heavy_sector and fair_value_share_incl_leases is not None and valuation_model == "DCF":
        fair_value_share = fair_value_share_incl_leases
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
        # ValuationResult is frozen - the headline swap above must also
        # replace the object OrdinaryMetrics.valuation actually stores,
        # not just these loose locals (which nothing downstream reads).
        valuation = dataclasses.replace(
            valuation, fair_value_share=fair_value_share, over_under_pct=over_under,
            val_status=val_status, val_color_key=val_color_key,
        )

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
        nonrecurring_note=nonrecurring_note,
        net_debt_incl_leases=net_debt_incl_leases,
        fair_value_share_incl_leases=fair_value_share_incl_leases,
        fair_value_share_excl_leases=fair_value_share_excl_leases,
        lease_heavy_sector=lease_heavy_sector,
        cost_of_debt=cost_of_debt,
        cost_of_debt_is_implied=cost_of_debt_is_implied,
        terminal_g=terminal_g,
        terminal_g_label=terminal_g_label,
        graham_value=graham_value,
        graham_eps=graham_eps,
        graham_eps_label=graham_eps_label,
        graham_tangible_bvps=graham_tangible_bvps,
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
    # V03: same "Normalized Income" normalization as compute_metrics() -
    # see docs/spec/issues/V03-normalize-nonrecurring-items.md.
    normalized_income = find_row(df_fin, ["Normalized Income"], default_val=float("nan"))
    preferred_dividends = find_row(df_fin, ["Preferred Stock Dividends", "Preferred Dividends"])
    diluted_shares = find_row(
        df_fin, ["Diluted Average Shares", "Diluted Shares Outstanding", "Average Shares"],
        default_val=float("nan"),
    )
    # V10 (docs/spec/issues/V10-graham-number-reproducible.md) - not parsed
    # anywhere in the Bank path before this.
    eps = find_row(df_fin, ["Diluted EPS", "Basic EPS"], default_val=float("nan"))

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
    # V01: goodwill wasn't parsed anywhere in the Bank path before this -
    # only Ordinary's compute_metrics() had it. Feeds tangible_equity below,
    # used by bank_valuation()'s roe<=0 floor (a goodwill-heavy bank's raw
    # bvps otherwise inflates that floor - see
    # docs/spec/issues/V01-tangible-equity-distress-triggers.md).
    goodwill = find_row(df_bal, ["Goodwill"], default_val=0.0)
    other_intangibles = find_row(df_bal, ["Other Intangible Assets"], default_val=0.0)

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
        normalized_income = normalized_income * fx_rate
        preferred_dividends = preferred_dividends * fx_rate
        cash_and_equiv = cash_and_equiv * fx_rate
        trading_assets = trading_assets * fx_rate
        htm_securities = htm_securities * fx_rate
        net_loans = net_loans * fx_rate
        loan_loss_allowance = loan_loss_allowance * fx_rate
        total_deposits = total_deposits * fx_rate
        total_borrowings = total_borrowings * fx_rate
        shareholders_equity = shareholders_equity * fx_rate
        goodwill = goodwill * fx_rate
        other_intangibles = other_intangibles * fx_rate
        common_dividends_paid = common_dividends_paid * fx_rate

    # V03: net_income_normalized feeds only the net_income_declining sin
    # below - reported (raw) net_income elsewhere is untouched (see
    # docs/spec/issues/V03-normalize-nonrecurring-items.md).
    net_income_normalized = normalized_income.fillna(net_income)
    nonrecurring_note = _nonrecurring_note(year_labels, net_income, net_income_normalized, normalized_income)

    # ── Bank sins checklist (condition checks + registry-driven scoring) ──
    # Moved to src/fundamental_express/domain/bank.py (condition checks) and
    # domain/sins.py (scoring) - docs/spec/refactor-tasks.md T14.
    sins, latest_equity, ltd_ratio, debt_to_equity = check_bank_sins(
        net_interest_income, shareholders_equity, credit_loss_provision,
        diluted_shares, net_loans, total_deposits, cash_and_equiv,
        non_interest_expense, commissions_income, net_income_normalized, total_borrowings,
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
    tangible_equity_series = shareholders_equity - goodwill - other_intangibles
    latest_tangible_equity = (
        tangible_equity_series.iloc[-1] if len(tangible_equity_series) else float("nan")
    )

    # V10 (docs/spec/issues/V10-graham-number-reproducible.md) - see the
    # identical Ordinary computation for the reasoning.
    graham_eps, graham_eps_label = eps_for_graham(info, eps.iloc[-1] if len(eps) else None)
    graham_tangible_bvps = (
        latest_tangible_equity / shares if shares > 0 and not pd.isna(latest_tangible_equity) else None
    )
    graham_value = graham_number(graham_eps, graham_tangible_bvps)

    valuation, val_extras = bank_valuation(
        required_return, beta, info, common_dividends_paid, diluted_shares,
        latest_equity, shares, net_income, price,
        tangible_equity=latest_tangible_equity,
        beta_is_fallback=data.get("beta_is_fallback", False),
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
    terminal_g = val_extras["terminal_g"]
    terminal_g_label = val_extras["terminal_g_label"]

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
        nonrecurring_note=nonrecurring_note,
        terminal_g=terminal_g,
        terminal_g_label=terminal_g_label,
        graham_value=graham_value,
        graham_eps=graham_eps,
        graham_eps_label=graham_eps_label,
        graham_tangible_bvps=graham_tangible_bvps,
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
    REIT_DEFAULT_CAP_RATE_SPREAD,
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
    avg_noi = val_extras["avg_noi"]
    avg_noi_years = val_extras["avg_noi_years"]
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
        avg_noi=avg_noi,
        avg_noi_years=avg_noi_years,
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

# Moved to src/fundamental_express/cli/catalysts.py and cli/args.py
# (docs/spec/refactor-tasks.md T22). Re-exported under their original names -
# analyzers.py imports CATALYSTS_PLACEHOLDER from here, and
# tests/test_verdict_scoring.py imports required_return_type from here.
from fundamental_express.cli.catalysts import CATALYSTS_PLACEHOLDER, resolve_catalysts_text  # noqa: E402
from fundamental_express.cli.args import required_return_type  # noqa: E402


# ── ORDINARY / BANK / REIT PDF REPORTS ──────────────────────────────────
# build_pdf_report()/build_bank_pdf_report()/build_reit_pdf_report() (one
# per asset class, each hardcoded to its own compute_*_metrics()) are gone -
# cli/single_ticker.py used to call build_pdf_report() unconditionally for
# every ticker regardless of sector (a bug: a Financial Services/REIT
# ticker silently got the Ordinary CAPM/WACC FCF-DCF instead of its real
# DDM/ROE-P-B or NAV model - EV/Net Debt/FCF are not meaningful for a
# bank's balance sheet). cli/single_ticker.py now routes through
# analyzers.AnalyzerFactory, same as cli/portfolio.py, so both entry points
# always agree on which model a given ticker gets.


# Moved to src/fundamental_express/cli/single_ticker.py (docs/spec/refactor-tasks.md T22).
if __name__ == "__main__":
    from fundamental_express.cli.single_ticker import main

    main()
