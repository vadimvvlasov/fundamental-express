"""Valuation models: CAPM/WACC/DCF, DDM, NAV, ROE-P-B, the REIT cap-rate
matrix, and the Forward Outlook proxy chain. Built incrementally
(docs/spec/refactor-tasks.md T12a-T12e) - each piece is self-contained
(reads only already-computed inputs, no interleaving with any
compute_*_metrics() sins-checklist) and lands here in its own commit.

T12a: compute_forward_outlook/_peg_assessment/_EMPTY_FORWARD_OUTLOOK.
T12b (this commit): REIT_CAP_RATE_MATRIX/_reit_cap_rate.
"""


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
