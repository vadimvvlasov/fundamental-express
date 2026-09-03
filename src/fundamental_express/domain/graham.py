"""Graham Number - V10 (docs/spec/issues/V10-graham-number-reproducible.md).

Makes the "Число Грэма" table that appeared in an earlier
Screen55_Comparative_Report reproducible in code - it was computed by hand
in a chat session before this, with no code path anywhere in this repo
(grep for "graham"/"Graham" across src/ turned up nothing prior to this
module). Uses tangible BVPS (V01's tangible_equity, not raw equity) -
the earlier hand-written table used raw BVPS, which a goodwill-heavy
company (ACN was the example on hand, ~$22.5B goodwill) overstates.

Purely informational ("справочно, вне основной методики" per the original
table's own framing) - never feeds the sins checklist or the DCF/DDM/
ROE-P-B verdict. Ordinary/Bank only; REIT is deliberately excluded (same
reasoning the original hand-written table already used: Graham's method
assumes an industrial/tangible-asset balance sheet, and REIT depreciation
distorts EPS the same way it distorts FFO).
"""

import math


def graham_number(eps, tangible_bvps):
    """√(22.5 × EPS × tangible_BVPS). Returns None when either input is
    non-positive (the formula is undefined - a negative-under-the-square-
    root case) rather than raising or silently coercing to 0/NaN."""
    if eps is None or tangible_bvps is None:
        return None
    if math.isnan(eps) or math.isnan(tangible_bvps):
        return None
    if eps <= 0 or tangible_bvps <= 0:
        return None
    return math.sqrt(22.5 * eps * tangible_bvps)


def eps_for_graham(info, latest_annual_eps):
    """(value, label) - prefers yfinance's own trailingEps (a real TTM
    figure) when present; falls back to the latest annual EPS this
    codebase already has, labeled "FY" rather than mislabeled "ttm" the
    way the original hand-written table's header claimed without
    verifying which figure was actually behind it. `label` is bare
    ("ttm"/"FY") - callers compose it into "EPS(...)" themselves."""
    info = info or {}
    trailing_eps = info.get("trailingEps")
    if trailing_eps is not None and not (isinstance(trailing_eps, float) and math.isnan(trailing_eps)):
        return float(trailing_eps), "ttm"
    return latest_annual_eps, "FY"
