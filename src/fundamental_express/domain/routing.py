"""Sector-routing helpers used by AnalyzerFactory. Moved verbatim out of
financial_analyzer.py/analyzers.py (docs/spec/refactor-tasks.md T08).
"""


def check_sector_suitability(ticker, info, force):
    """No sector is restricted anymore - Financial Services (banks, Step 2)
    and REIT industries (Step 3) both got their own real specialized
    engines (compute_bank_metrics()/compute_reit_metrics()) and are routed
    to them natively by AnalyzerFactory before this function is ever called
    for that ticker (see its docstring). This always returns (None, None).

    Kept in place - rather than deleted - for two reasons: it's the hook a
    future restricted sector would reuse (raise UnsupportedSectorError as
    before), and OrdinaryAnalyzer's warning-banner rendering path in
    build_markdown_report()/build_pdf_report() stays reachable code (even
    though no live sector currently triggers it) without touching that
    tested Ordinary rendering.
    """
    return None, None


def _is_reit(info):
    """Spec Section 1.1 routing marker - industry/sector text containing a
    REIT keyword, independent of check_sector_suitability()'s old
    sector-gated rule (kept only for the now-dormant warning-banner path,
    see that function's docstring)."""
    industry = str(info.get("industry") or "").lower()
    sector = str(info.get("sector") or "").lower()
    return "reit" in industry or "real estate investment trust" in industry or "real estate investment trust" in sector


_LEASE_HEAVY_KEYWORDS = (
    "retail", "grocery", "department store", "specialty retail",
    "airline", "restaurant",
)


def _is_lease_heavy(info):
    """V04 (docs/spec/issues/V04-lease-adjusted-net-debt.md) - a small
    starter keyword list (retail/grocery/airline/restaurant) deciding
    which sector gets the lease-inclusive fair value as the report's
    headline number instead of just a secondary figure. Deliberately not
    exhaustive (hospitality, healthcare facilities, telecom towers are
    real lease-heavy industries not covered here) - see
    docs/spec/issues/follow-ups.md#fu-02-lease-heavy-sector-taxonomy."""
    industry = str(info.get("industry") or "").lower()
    sector = str(info.get("sector") or "").lower()
    haystack = f"{industry} {sector}"
    return any(kw in haystack for kw in _LEASE_HEAVY_KEYWORDS)
