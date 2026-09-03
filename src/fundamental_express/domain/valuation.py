"""Valuation models: CAPM/WACC/DCF, DDM, NAV, ROE-P-B, the REIT cap-rate
matrix, and the Forward Outlook proxy chain. Built incrementally
(docs/spec/refactor-tasks.md T12a-T12e) - each piece is self-contained
(reads only already-computed inputs, no interleaving with any
compute_*_metrics() sins-checklist) and lands here in its own commit.

T12a: compute_forward_outlook/_peg_assessment/_EMPTY_FORWARD_OUTLOOK.
T12b: REIT_CAP_RATE_MATRIX/_reit_cap_rate.
T12c: ordinary_dcf_valuation (CAPM/WACC/DCF, Ordinary v3 DDM auto-switch,
sensitivity matrix).
T12d: bank_valuation (DDM or ROE/P-B).
T12e (this commit): reit_nav_valuation (NAV).
"""

import math

import pandas as pd

from fundamental_express.domain.metrics import ValuationResult


def _regression_cagr(values, lo, hi, default):
    """Multi-year log-linear regression CAGR (V02,
    docs/spec/issues/V02-regression-cagr.md) - replaces the old
    endpoint-to-endpoint `(values[-1]/values[0])**(1/(n-1)) - 1` formula,
    which ignored every year between the first and last. Fits a line to
    log(value) vs. year index by ordinary least squares; the slope,
    exponentiated back, is the annualized growth rate.

    Degenerates to the exact old endpoint formula when len(values) == 2
    (provable algebraically: the OLS slope on two points x=[0,1],
    y=[log(v0), log(v1)] reduces to log(v1/v0), so exp(slope)-1 ==
    v1/v0 - 1) - callers with only 2 historical years see no behavior
    change.

    Falls back to `default` when there are fewer than 2 values, or when
    *any* value in the window is non-positive (log undefined) - not just
    the first/last, unlike the old formula, which never looked at the
    values in between anyway.
    """
    values = list(values)
    if len(values) < 2 or any(v <= 0 for v in values):
        return default
    n = len(values)
    xs = range(n)
    log_ys = [math.log(v) for v in values]
    mean_x = sum(xs) / n
    mean_y = sum(log_ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    if var_x == 0:
        return default
    cov_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, log_ys))
    slope = cov_xy / var_x
    growth = math.exp(slope) - 1
    return max(lo, min(hi, growth))


def ordinary_dcf_valuation(
    fcf, price, shares, beta, required_return, latest_debt, net_debt,
    latest_equity, diluted_shares, cash_dividends_paid, info,
    tangible_equity=None,
):
    """CAPM/WACC/DCF fair value, with the Ordinary v3 auto-switch to DDM
    for a dividend-paying company with a distorted capital structure (spec
    docs/spec/step4-ordinary-v3-implementation-spec.md Section 2.3), plus
    the WACC/growth sensitivity matrix. Moved verbatim out of
    compute_metrics() - every input here was already computed earlier in
    that function (ahead of the sins checklist), never derived by this
    function itself, so the split is a pure move, not a redesign.

    Returns (ValuationResult, extras) - extras carries every other
    valuation-derived value compute_metrics()'s return dict needs
    (wacc, cagr, proj_years, projected_fcfs, pv_fcfs, enterprise_value,
    equity_value, sensitivity_headers, sensitivity_rows, cagr_div,
    dps_last, debt_to_equity_ratio) that doesn't fit ValuationResult's
    cross-asset-class shape.
    """
    fcf_values = fcf.values
    cagr = _regression_cagr(fcf_values, 0.02, 0.15, 0.05)

    rf_rate = 0.04
    erp = 0.05
    # --required-return lets the investor override CAPM entirely with their
    # own required rate of return, bypassing the beta-driven Ke formula.
    cost_of_equity = required_return if required_return is not None else rf_rate + beta * erp
    cost_of_debt = 0.045
    tax_rate = 0.21
    after_tax_debt = cost_of_debt * (1 - tax_rate)

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
    info = info or {}
    dividend_yield = info.get("dividendYield") or 0.0
    dividend_rate = info.get("dividendRate") or 0.0
    pays_dividends = dividend_yield > 0 or dividend_rate > 0
    # V01: D/E and the distress trigger use tangible equity (goodwill and
    # other intangibles stripped out) - a goodwill-heavy balance sheet can
    # otherwise understate D/E enough to miss the DDM switch a genuinely
    # distressed (on a tangible basis) company should get. tangible_equity
    # defaults to None for callers that don't pass it (falls back to raw
    # equity - no distortion assumed when the caller has no goodwill data).
    equity_for_de = (
        tangible_equity if tangible_equity is not None and not pd.isna(tangible_equity) else latest_equity
    )
    debt_to_equity_ratio = (
        latest_debt / equity_for_de if equity_for_de > 0 and not pd.isna(latest_debt) else None
    )
    capital_distorted = (
        latest_equity <= 0
        or equity_for_de <= 0
        or (debt_to_equity_ratio is not None and debt_to_equity_ratio > 2.0)
    )
    use_ddm = pays_dividends and capital_distorted and not diluted_shares.isna().all()

    if use_ddm:
        dps_series = (cash_dividends_paid.abs() / diluted_shares).dropna()
        dps_window = dps_series.iloc[-4:] if len(dps_series) >= 2 else dps_series
        cagr_div = _regression_cagr(dps_window.values, 0.02, 0.10, 0.05)
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

    valuation = ValuationResult(
        price=price,
        fair_value_share=fair_value_share,
        over_under_pct=over_under,
        val_status=val_status,
        val_color_key=val_color_key,
        beta=beta,
        valuation_model=valuation_model,
        cost_of_equity=cost_of_equity,
        required_return_used=required_return is not None,
    )
    extras = {
        "wacc": wacc,
        "cost_of_debt_after_tax": after_tax_debt,
        "equity_weight": w_equity,
        "debt_weight": w_debt,
        "cagr": cagr,
        "proj_years": proj_years,
        "projected_fcfs": projected_fcfs,
        "pv_fcfs": pv_fcfs,
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "sensitivity_headers": sensitivity_headers,
        "sensitivity_rows": sensitivity_rows,
        "cagr_div": cagr_div,
        "dps_last": dps_last,
        "debt_to_equity_ratio": debt_to_equity_ratio,
    }
    return valuation, extras


def bank_valuation(
    required_return, beta, info, common_dividends_paid, diluted_shares, latest_equity, shares, net_income, price,
    tangible_equity=None,
):
    """DDM (dividend-paying bank) or ROE/P-B (non-payer) fair value (spec
    Section 5, docs/spec/step2-bank-analyzer-implementation-spec.md). Moved
    verbatim out of compute_bank_metrics() - every input here was already
    computed earlier in that function.

    Returns (ValuationResult, extras) - extras carries cagr_div/dps_last
    (DDM path only, else None) and bvps/roe (ROE/P-B path only, else None).
    """
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
        cagr_div = _regression_cagr(dps_window.values, 0.01, 0.08, 0.03)
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
                # V01: the floor uses tangible bvps - equity doesn't cancel
                # out of a flat "0.1 * bvps" the way it does in the roe>0
                # branch below, so a goodwill-heavy bank gets an inflated
                # floor if raw bvps is used here. Falls back to raw bvps
                # when the caller has no goodwill data (tangible_equity=None).
                bvps_tangible = (
                    tangible_equity / shares
                    if tangible_equity is not None and not pd.isna(tangible_equity) and shares > 0
                    else bvps
                )
                fair_value_share = 0.1 * bvps_tangible
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

    valuation = ValuationResult(
        price=price,
        fair_value_share=fair_value_share,
        over_under_pct=over_under,
        val_status=val_status,
        val_color_key=val_color_key,
        beta=beta,
        valuation_model=valuation_model,
        cost_of_equity=cost_of_equity,
        required_return_used=required_return is not None,
    )
    extras = {
        "cagr_div": cagr_div,
        "dps_last": dps_last,
        "bvps": bvps,
        "roe": roe,
    }
    return valuation, extras


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


def reit_nav_valuation(info, noi, cash, receivables, construction_in_progress, total_liab, shares, price, ffo, diluted_shares, beta):
    """NAV (Net Asset Value) fair value (spec Section 5) - REITs get no
    CAPM cost of equity or DCF/DDM model switch (classical DCF is
    meaningless for a pass-through of rental cash flow, see spec Section
    0/2), so ValuationResult.valuation_model/cost_of_equity/
    required_return_used all stay at their None default here. Moved
    verbatim out of compute_reit_metrics() - every input here was already
    computed earlier in that function.

    Returns (ValuationResult, extras) - extras carries cap_rate/
    cap_rate_label/property_value/nav/ffo_per_share/p_ffo.
    """
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

    valuation = ValuationResult(
        price=price,
        fair_value_share=fair_value_share,
        over_under_pct=over_under,
        val_status=val_status,
        val_color_key=val_color_key,
        beta=beta,
    )
    extras = {
        "cap_rate": cap_rate,
        "cap_rate_label": cap_rate_label,
        "property_value": property_value,
        "nav": nav,
        "ffo_per_share": ffo_per_share,
        "p_ffo": p_ffo,
    }
    return valuation, extras


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
