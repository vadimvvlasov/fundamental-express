# V03 — Strip explicit non-recurring items from FCF/Net Income before DCF and the sins checklist

## Problem
Ordinary and Bank Net Income / FCF are read from yfinance as reported
(GAAP), with no adjustment for one-off items (impairments, gains on asset
sales, restructuring/M&A charges, litigation settlements). Those numbers
feed two places that both assume the input reflects ongoing business
performance:

- The DCF/DDM growth projections (`ordinary_dcf_valuation`,
  `valuation.py:41` FCF CAGR; `financial_analyzer.py` sins checklist's
  `net_income_declining`/similar checks).
- The bank sins checklist's `net_income_declining` check
  (`domain/bank.py:132-136`) and equivalent Ordinary checks.

A one-off gain or loss in either the first, last, or a middle year of the
historical window can flip a "declining" sin on/off, or move the CAGR feed
into V02's projection, for reasons that have nothing to do with the
business's actual trajectory.

This codebase already has a working precedent for exactly this kind of
normalization — it just isn't applied outside REIT. `compute_reit_metrics`
explicitly subtracts one named non-recurring item from Net Income to
compute FFO: `ffo = net_income + d_and_a - gain_on_sale`
(`financial_analyzer.py:698`, `gain_on_sale` sourced from `"Gain on Sale of
Real Estate"` / `"Gain on Sale of Investment Property"` /
`"Gain on Sale of Business"` rows, `financial_analyzer.py:632-634`).

## Acceptance Criteria
- [ ] For the Ordinary and Bank code paths, an explicit list of yfinance
      row names is read (mirroring the REIT precedent) for at least:
      impairment/write-downs, gain/loss on sale of assets or business, and
      restructuring/M&A charges — using whatever exact row names yfinance
      exposes for these (to be confirmed against real fetched data, same
      as the REIT rows were).
- [ ] A `net_income_normalized` (and, where FCF is affected — e.g. an
      impairment flowing through operating cash flow — an equivalent
      normalized FCF) is computed by adding back/removing the identified
      rows, and is what feeds: the FCF CAGR (`valuation.py:41`), the
      Ordinary DCF's `fcf` input, and the `net_income_declining` /
      `nii_declining`-style sins in both `ordinary.py` and `bank.py`.
- [ ] The *reported* (unadjusted) Net Income and FCF still appear in the
      "Экспресс-анализ финансовых результатов и баланса" table as they do
      today — this task adds a normalized figure used internally by the
      model, it does not hide or replace the raw historical table a
      reviewer can already sanity-check by eye.
- [ ] When at least one non-recurring item was found and subtracted for a
      given year, the report visibly says so — a new line under the
      DCF/sins sections naming the item and amount (e.g. "Скорректировано:
      исключён единоразовый Impairment за 2023 (−340 млн)"), so a reviewer
      can point at the screen and confirm which years were touched and by
      how much, not just trust an unlabeled number swap.
- [ ] When no such row is found for a ticker (the common case — most
      companies don't report one every year), behavior is byte-identical
      to today: `net_income_normalized == net_income`,
      `fcf_normalized == fcf`, no new disclosure line rendered.
- [ ] `pytest -q` passes, with new tests covering: a fixture with a
      one-off impairment in a middle year (confirms the
      `net_income_declining` sin no longer fires when only the raw,
      unadjusted number would have declined), and a fixture with no such
      row present (confirms the no-op case above).
- [ ] `tests/golden/` snapshots reviewed; any ticker whose sins/CAGR
      changed because of this fix is called out explicitly in the PR
      description, same discipline as V01/V02.

## Edge Cases Considered
- **Item present in Net Income's flow but not in Free Cash Flow** (a
  non-cash impairment write-down affects reported Net Income but is
  already added back inside Cash Flow From Operations, so FCF may not
  need the same subtraction FCF already reflects it as an add-back). The
  fix must not double-adjust FCF for a purely non-cash item — only adjust
  FCF for rows that genuinely represent a cash inflow/outflow (e.g. an
  actual gain-on-sale proceeds timing mismatch), following the same
  reasoning already embedded in the REIT FFO formula's asymmetric
  treatment of `d_and_a` (added back) vs. `gain_on_sale` (subtracted).
- **Multiple non-recurring rows in the same year** (e.g. both an
  impairment and a restructuring charge). The normalization must sum all
  identified items for that year, and the disclosure line must list all
  of them, not just the largest.
- **A row exists in yfinance's data but is `NaN` for most years and a real
  number for one.** Must not be treated as "row not found" (which would
  silently keep the raw, unadjusted number for the one year that actually
  has data) — `find_row`'s existing per-cell NaN handling already
  distinguishes "row missing entirely" from "row present, some years
  blank"; this task must use that distinction correctly, not paper over
  it.
- **`--allow-sample` fixture data.** `src/fundamental_express/data/sample.py`
  has no unusual-items rows today — confirm the no-op path (no row found
  → no adjustment) is what sample mode exercises, so
  `python financial_analyzer.py <ticker> --allow-sample` keeps working
  unchanged.
- **A ticker where the "non-recurring" item recurs every year** (e.g. a
  serial acquirer with restructuring charges in 4 of 5 years). This is a
  real business characteristic, not noise — the fix should not have a
  rule that silently treats a *recurring* "unusual item" line as always
  removable. Out of scope to build a recurrence-detection heuristic here
  (see Out of Scope); this task normalizes whatever explicit rows are
  found, year by year, without judging whether the pattern itself is a
  red flag — that judgment stays with the reviewer, informed by the new
  disclosure line.

## Out of Scope
- Detecting a non-recurring item that yfinance does *not* break out into
  its own row (e.g. one buried inside "Other Operating Expenses") — would
  need text-parsing of actual filings or a different data source →
  see [FU-01](./follow-ups.md#fu-01-nonrecurring-detection).
- Any heuristic for flagging a *recurring* "unusual item" pattern as a new
  sin of its own (e.g. "restructuring charges in 4 of the last 5 years") —
  a genuinely useful idea, but a new checklist rule, not a normalization
  fix, and not implied by this task.
