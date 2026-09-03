# V09 — Sector-bucketed terminal growth instead of one flat 2.5% for every company

## Problem
`terminal_g = 0.025` is used for the Gordon Growth terminal value in both
`ordinary_dcf_valuation` (`valuation.py:77`) and `bank_valuation`
(`valuation.py:227`, a separate literal, not a shared reference — same
duplication pattern already found and corrected for in
[V06](./V06-reit-cap-rate-rate-regime.md)'s `rf_rate`). A mature utility
and a growth-stage tech company get an identical assumption for what
happens to their cash flow growth in year 6 and beyond, which is one of
the most sensitive single inputs in any DCF (the sensitivity matrix
already rendered in every report — `sections_ordinary.py`'s "г / WACC"
table — exists specifically because this input moves fair value so much).

## Acceptance Criteria
- [ ] A single module-level `TERMINAL_GROWTH_MATRIX` (mirroring
      `REIT_CAP_RATE_MATRIX`'s existing shape and lookup pattern,
      `valuation.py:308-313`/`320-334`) maps sector/industry keywords to a
      terminal growth rate, with a conservative default for anything
      unmatched.
- [ ] Both `ordinary_dcf_valuation` and `bank_valuation`'s `terminal_g =
      0.025` literals are replaced with a lookup against this matrix,
      keyed off `info`. This removes the duplication called out in
      Problem as a side effect, not as this task's main goal.
- [ ] The unmatched-sector default resolves to exactly `2.5%` — today's
      value — so any ticker whose sector/industry text doesn't match a
      bucket produces a byte-identical golden snapshot to before this
      task.
- [ ] The existing safety check `if wacc > terminal_g` (`valuation.py:80`,
      and its DDM/bank equivalents) is preserved unchanged — a
      sector-specific terminal growth must still be checked against that
      ticker's own WACC/Ke before use, not assumed always-safe because a
      table produced it.
- [ ] The rendered report's terminal growth line (currently a flat
      "Терминальный темп роста: 2.5%" in both Ordinary and Bank sections)
      shows which bucket matched (e.g. "2.5% (default)" vs. a named
      bucket like "1.5% (Utilities — зрелый сектор)"), so a reviewer can
      see why a given company got the rate it got.
- [ ] `pytest -q` passes, with tests for: a matched sector producing a
      non-default rate, the unmatched-sector default producing exactly
      2.5%, and the `wacc > terminal_g` guard still firing correctly for
      a sector bucket whose rate is close to a low-beta company's WACC.
- [ ] `tests/golden/` snapshots reviewed; any ticker whose sector matches
      a new non-default bucket is called out explicitly in the PR
      description (expected for tickers already tagged e.g. "Utilities"
      in their `info`, given the sector name appears directly in several
      already-generated Screen55 report rows: NJR, BKH, EVRG, CMS, LNT).

## Edge Cases Considered
- **A sector bucket's rate ends up above a low-growth company's own WACC**
  for a specific ticker, triggering the existing `if wacc > terminal_g
  else 0.0` fallback to a zero terminal value. This is already-existing
  behavior for the flat 2.5% case too (any WACC ≤ 2.5% hits it today) —
  this task doesn't change that guard, just what value it's guarding
  against, so no new handling is needed, only confirmation the guard
  still triggers correctly per the acceptance criterion above.
- **A company's `info` sector/industry text matches keywords for more than
  one bucket.** Reuse `_reit_cap_rate`'s existing "first match wins,
  matrix-order-dependent" convention (`valuation.py:328-333`) rather than
  inventing a new resolution rule — keeps the two matrices' behavior
  consistent for anyone reading both.
- **Bank and Ordinary use the same matrix, but a bank's terminal growth
  intuition differs from an industrial company's** (e.g. deposit growth
  vs. unit growth). This task uses one shared matrix for both, same as
  `RF_RATE` is shared across both after V06 — if bank-specific buckets
  turn out to be needed, that's a refinement to the matrix's entries, not
  a reason to fork two separate matrices now without evidence they should
  diverge.

## Out of Scope
- Deriving terminal growth from analyst long-term consensus estimates
  per company instead of a sector bucket → see
  [FU-06](./follow-ups.md#fu-06-consensus-terminal-growth) — no such data
  source is currently wired into the DCF terminal-value calculation
  (Forward P/E and PEG consensus exist only for the separate, informational
  Forward Outlook section, `compute_forward_outlook`).
