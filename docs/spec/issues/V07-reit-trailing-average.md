# V07 — Use a trailing multi-year average NOI for REIT NAV, not one snapshot year

## Problem
`reit_nav_valuation` derives the entire property portfolio value from a
single year: `latest_noi = noi.iloc[-1]`, `property_value = latest_noi /
cap_rate` (`valuation.py:349-350`). A one-off vacancy spike, a lease
expiration cluster, or an unusually strong single year moves the *entire*
NAV fair value, since `property_value` is by far the largest term in
`nav = property_value + cash + receivables + cip - total_liab`
(`valuation.py:356`).

**Correction to how this was originally filed:** the backlog entry named
this "трейлинг-среднее NOI/FFO" as if both fed the fair value calculation.
They don't, equally. Only `noi.iloc[-1]` feeds `property_value`, which
feeds `fair_value_share`. `ffo.iloc[-1]` (`valuation.py:368`) only feeds
`ffo_per_share`/`p_ffo` — an informational trailing multiple shown in the
report and used elsewhere for cross-ticker comparison in the portfolio
table (`P/FFO 13.6x` column, `cli/portfolio.py`), not part of the fair
value number itself. Smoothing FFO the same way as NOI would change what
that comparison multiple *means* (a "P/FFO" that's actually "P/3yr-avg-FFO"
is a different, non-standard metric), which isn't something the original
filer weighed. This task is scoped to NOI only; see Acceptance Criteria
and Out of Scope.

## Acceptance Criteria
- [ ] `property_value` is computed from a trailing multi-year average of
      `noi` (e.g. last 2-3 available years) instead of `noi.iloc[-1]`
      alone. Exact window size is an implementation decision but must be
      documented in a code comment the way other lookback windows in this
      codebase are (e.g. the dividend CAGR's `iloc[-4:]` comment at
      `valuation.py:126`).
- [ ] When fewer years of NOI are available than the target window (e.g.
      only 1-2 years of history), the average degrades gracefully to
      however many years exist — never crashes, never fabricates a year.
- [ ] `ffo_per_share`/`p_ffo` are explicitly **unchanged** — still computed
      from `ffo.iloc[-1]` as today. A test asserts this stays true so a
      future edit doesn't accidentally couple the two.
- [ ] Given a fixture with a clear NOI outlier in the most recent year
      (spike or dip) against a stable multi-year trend, the NAV fair value
      after this fix differs from today's single-year calculation by a
      material amount in a unit test — demonstrating the fix changes
      behavior in the case it exists for.
- [ ] The report's NAV bridge section shows which NOI figure was used
      (e.g. "NOI (среднее за N лет)" instead of the current single-year
      label), so a reviewer can tell the methodology changed by reading
      the report, not by re-deriving the number.
- [ ] `pytest -q` passes, with tests for: the outlier-smoothing case, the
      short-history degradation case, and the FFO/P-FFO no-change
      guarantee.
- [ ] `tests/golden/` REIT snapshot reviewed; the fair value is expected
      to change for any golden fixture with multi-year NOI variance —
      called out explicitly in the PR description.

## Edge Cases Considered
- **Only one year of NOI available at all** (e.g. recent IPO/spin-off
  REIT). Average of one value equals that value — same as today's
  `iloc[-1]` behavior, no special-case needed beyond the graceful
  degradation already required above.
- **A negative NOI year inside the averaging window** (a REIT can have a
  genuinely bad year without invalidating the average — unlike V02's
  log-regression CAGR, a simple arithmetic mean has no issue with a
  negative or zero value in the window, so no fallback logic is needed
  here that V02 needed for its regression approach).
- **`cap_rate` itself may also become rate-regime-aware** if
  [V06](./V06-reit-cap-rate-rate-regime.md) lands — the two tasks are
  independent (one smooths the NOI numerator, the other adjusts the cap
  rate denominator) and can land in either order without conflict, but a
  reviewer looking at a NAV fair value after both land should expect both
  changes reflected, not just one.

## Out of Scope
- Applying the same multi-year averaging to `ffo`/`p_ffo` — deliberately
  excluded per the Problem correction above; changing what "P/FFO" means
  as a comparison metric is a separate decision with cross-portfolio
  implications (`cli/portfolio.py`'s comparative table), not implied by
  fixing the NAV fair value's NOI sensitivity.
- Applying the same multi-year-average pattern to Ordinary/Bank FCF and
  dividend CAGR → that's already covered by
  [V02](./V02-regression-cagr.md) (which uses a regression, not a simple
  average — a deliberately different smoothing method for a different
  metric shape; not unified here).
