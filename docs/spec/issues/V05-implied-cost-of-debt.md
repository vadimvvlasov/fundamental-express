# V05 — Derive cost of debt (Kd) from the company's own interest expense, not a flat 4.5%

## Problem
`ordinary_dcf_valuation` hardcodes `cost_of_debt = 0.045` for every ticker
(`valuation.py:33`), feeding directly into the WACC calculation
(`after_tax_debt = cost_of_debt * (1 - tax_rate)`, same block). An
investment-grade company and a heavily-leveraged, junk-rated company get
identical Kd, even though the report already fetches the input needed to
tell them apart: `interest_expense` is parsed at
`financial_analyzer.py:198-203` (used today only for the Interest Coverage
Ratio smart-bypass check) but is never passed into
`ordinary_dcf_valuation` or used to inform Kd.

## Acceptance Criteria
- [ ] `ordinary_dcf_valuation` gains an `interest_expense` (or
      `implied_cost_of_debt`, computed by the caller) parameter.
- [ ] When `interest_expense` and `latest_debt` are both available and
      `latest_debt > 0`, `implied_kd = interest_expense / latest_debt`,
      clamped to a sane range (e.g. 2%-12% — exact bounds are an
      implementation decision, but must be documented in a code comment
      the way the existing WACC clamp is: `valuation.py:64`,
      `wacc = max(0.05, min(0.15, wacc))`).
- [ ] When `interest_expense` is unavailable, `NaN`, or `latest_debt <= 0`,
      `cost_of_debt` falls back to today's flat `0.045` — unchanged
      behavior for that ticker, not a crash or a fabricated rate.
- [ ] The rendered report's WACC breakdown (wherever `Kd` is currently
      shown as "Kd=4.5%... фиксированные допущения методики, не
      специфичны для компании" — see the RF report's DCF section) states
      which of the two cases applied: an implied rate computed from the
      company's own interest expense, or the flat fallback — with the
      exact wording changed between the two cases so a reviewer can tell
      which one was used without inspecting the calculation.
- [ ] Given a fixture with `interest_expense = 45M` and `latest_debt =
      1B`, the report shows Kd = 4.5% *labeled as company-implied*, not
      the fallback — and a second fixture with the same Kd value arrived
      at through the *fallback* path (no interest expense data) shows the
      fallback label instead. This distinguishes "coincidentally the same
      number" from "used the fallback," which a pure value-equality check
      cannot.
- [ ] `pytest -q` passes, with tests for: implied Kd within bounds,
      implied Kd clamped when it would fall outside bounds (e.g. a company
      paying near-zero effective interest due to old low-rate debt),
      and the missing-data fallback.
- [ ] `tests/golden/` snapshots reviewed; any ticker whose Kd/WACC changed
      is called out in the PR description.

## Edge Cases Considered
- **Interest expense reflects a blended rate across old and new debt
  issued at very different times** (e.g. legacy bonds from a low-rate
  environment plus recent debt at current rates). The implied rate will
  understate the marginal cost of *new* debt. This is a known limitation
  of the implied-rate approach in general, not a bug to fix here — the
  clamp bounds exist partly to keep this from producing an absurd number,
  and the disclosure label lets a reviewer discount it accordingly.
- **A company with near-zero or negative net interest expense** (net
  interest income exceeds expense, common for cash-rich companies with
  little debt — e.g. a company reporting "Interest Expense Non Operating"
  net of interest income). `implied_kd` could come out negative or
  implausibly low; the clamp floor handles this the same way it handles
  any out-of-range value, falling back to the floor bound rather than a
  negative cost of debt.
- **`latest_debt` is very small relative to `interest_expense`** (e.g. debt
  paid down mid-year but interest expense reflects the prior year's larger
  balance). Implied Kd could spike well above the clamp ceiling — handled
  by the same clamp, with the disclosure still showing "company-implied"
  since the fallback wasn't triggered, so the reviewer sees a
  clamped-but-labeled number, not a silent fallback.
- **`--allow-sample` fixture data.** Confirm sample data either has no
  interest expense row (falls back to 4.5%, unchanged) or has one that
  produces a sane implied rate — either way `python financial_analyzer.py
  <ticker> --allow-sample` must keep completing.

## Out of Scope
- Using actual credit-rating-based bond spreads instead of an
  interest-expense-implied rate → see
  [FU-03](./follow-ups.md#fu-03-rating-based-kd) — this task only uses
  data already available from the company's own financials, no new data
  source.
