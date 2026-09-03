# V02 — Replace endpoint-to-endpoint CAGR with a multi-year regression

## Problem
Three growth-rate calculations in `src/fundamental_express/domain/valuation.py`
use only the first and last year of a historical window and ignore every
year in between:

- FCF CAGR feeding the Ordinary DCF projection: `valuation.py:41`
  (`cagr = (fcf_values[-1] / fcf_values[0]) ** (1 / (len(fcf_values) - 1)) - 1`)
- Dividend CAGR for the Ordinary v3 DDM switch: `valuation.py:131`
- Dividend CAGR for the Bank DDM model: `valuation.py:249`

A single anomalous year at either end of the window (an asset sale, a
one-off impairment, a COVID-year dip) moves the CAGR used to project the
next five years, even if every year in between shows a clean, different
trend. The existing clamps (`max(0.02, min(0.15, cagr))` etc.) limit how
far a bad CAGR can push the final number, but don't fix a distorted
starting point within those bounds.

## Acceptance Criteria
- [ ] A shared helper (e.g. `_regression_cagr(values)`) replaces all three
      endpoint calculations, fitting a line to `log(value)` vs. year index
      and converting the slope back to an annualized growth rate — used at
      all three call sites (`valuation.py:41`, `131`, `249`).
- [ ] **Two-point degeneration:** given exactly 2 historical values, the
      regression result is numerically identical (within floating-point
      tolerance) to the old endpoint formula — this is a math property to
      assert in a unit test, not an approximation. No behavior change for
      any ticker whose fetched history is only 2 years.
- [ ] **Materially different result for a real multi-year distortion:**
      given a 5-year fixture where years 1 and 5 are outliers but years
      2-4 show a clear, different trend, the regression CAGR differs from
      the old endpoint CAGR by more than 1 percentage point in a unit
      test — demonstrating the fix actually changes behavior in the case
      it was written for, not just in theory.
- [ ] Existing clamps stay exactly where they are (2-15% FCF, 1-8%/2-10%
      dividend depending on branch) — only the pre-clamp raw CAGR
      calculation changes, not the safety bounds around it.
- [ ] The methodology-disclosure text in the rendered report changes to
      say so, so a reviewer can see the method on screen, not just trust
      the number: `sections_ordinary.py:225`
      ("CAGR роста FCF: ... (историческая, ограничена 2-15%)") and the
      equivalent Bank/Ordinary DDM dividend-CAGR lines
      (`sections_bank.py:41`, `sections_ordinary.py:208`) get a
      parenthetical noting the multi-year regression (exact wording is an
      implementation choice, but it must be visibly different from the
      current text).
- [ ] `pytest -q` passes, with new tests covering: 2-point degeneration,
      the outlier-year case, and the negative/zero-FCF-in-window fallback
      (see Edge Cases).
- [ ] `tests/golden/` snapshots reviewed and any changed ticker's new CAGR
      called out explicitly in the PR description (same review discipline
      as V01 — this task is expected to change some golden numbers, that's
      the point).

## Edge Cases Considered
- **Fewer than 2 usable years** (e.g. recent IPO). Already falls back to a
  fixed default (`cagr = 0.05` at `valuation.py:44`, `cagr_div = 0.05`/`0.03`
  at the two dividend sites) — this task must not touch that branch, only
  the `len(fcf_values) >= 2` path.
- **A negative or zero value *inside* the window, not just at the
  endpoints.** The current endpoint check only guards `fcf_values[0] > 0
  and fcf_values[-1] > 0` — a middle year can already be negative today
  without breaking anything, because only the two endpoints are read. A
  log-regression reads every year, and `log()` of a non-positive value is
  undefined. The regression helper must detect any non-positive value
  anywhere in the window and fall back to the existing default CAGR for
  that branch, not crash and not silently skip the bad year.
- **Window-size mismatch between call sites.** The FCF CAGR uses however
  many years `get_company_data` returns (currently effectively the
  overlap of financials/balance/cashflow — see
  `_align_statement_years` in `data/parsing.py`), while the dividend CAGR
  sites explicitly slice to the last 4 years (`dps_series.iloc[-4:]`,
  `valuation.py:126`, `244`). This task keeps each call site's existing
  window size — it changes *how* the CAGR is computed from a window, not
  *which* window each site uses. Unifying window sizes is a separate
  decision, not implied by this task.
- **All values in the window identical (zero growth).** Regression slope
  is 0 → CAGR 0%, then clamped up to the 2%/1% floor same as today's
  endpoint formula would produce for a flat series. No special-case
  needed, just confirm the existing clamp still applies after the
  calculation swap.

## Out of Scope
- Applying the same regression smoothing to REIT NOI/FFO (a different
  metric, different call site, different code path) → see
  [V07](./V07-reit-trailing-average.md), which already covers that.
- Any change to the clamp bounds themselves (2-15%, 1-8%, 2-10%) — those
  are an existing, separately-decided methodology choice, not part of
  "how do we compute the raw growth rate" that this task addresses.
