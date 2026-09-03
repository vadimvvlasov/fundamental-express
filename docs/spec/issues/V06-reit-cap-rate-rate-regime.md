# V06 — Tie REIT cap rates to the risk-free rate instead of a permanent flat spread

## Problem
`REIT_CAP_RATE_MATRIX` (`valuation.py:308-313`) hardcodes four flat cap
rates (5.5%-7.0%) by property-type keyword, with no link to interest
rates. REIT valuation is historically rate-sensitive (cap rate ≈
risk-free rate + a property-type spread); a matrix frozen at today's rates
will misprice every REIT the day rates move meaningfully, in either
direction, without anyone touching this code.

**Correction to how this was originally filed:** the backlog entry this
issue came from assumed a shared `rf_rate` constant "already exists in the
Ordinary/Bank models" that this task could just reuse. That's not
accurate — `rf_rate = 0.04` is hardcoded separately *inside*
`ordinary_dcf_valuation` (`valuation.py:32`), and `bank_valuation`'s
`_cost_of_equity()` hardcodes the same `0.04` literal again, independently
(`valuation.py:221` area, `ke = 0.04 + beta * 0.05`). There is no single
named constant today — it's the same number typed twice. This task
therefore has a prerequisite step it wasn't originally scoped to include.

## Acceptance Criteria
- [ ] A single module-level constant (e.g. `RF_RATE = 0.04`) is added to
      `domain/valuation.py` and both `ordinary_dcf_valuation`'s
      `rf_rate = 0.04` and `bank_valuation`'s inline `0.04` are replaced
      with references to it. This step alone must be a pure refactor —
      `pytest -q` and every existing golden snapshot byte-identical
      before touching the REIT cap rate logic.
- [ ] `_reit_cap_rate`'s matrix values (5.5%/6.0%/6.5%/7.0%) are
      reinterpreted as **spreads over `RF_RATE`**, not standalone rates:
      `cap_rate = spread + RF_RATE`. With `RF_RATE` at today's `0.04`,
      the four resulting cap rates must come out numerically identical
      to today's hardcoded 5.5%/6.0%/6.5%/7.0% (i.e. the stored spreads
      are 1.5%/2.0%/2.5%/3.0%) — this task changes *what the number is
      derived from*, not what it evaluates to today.
- [ ] Given a test that changes `RF_RATE` (e.g. monkeypatches it to 0.06),
      the REIT NAV fair value for a fixture ticker changes accordingly —
      proving the wiring is live, not cosmetic.
- [ ] The REIT report's cap rate disclosure line
      (wherever `cap_rate_label` is rendered) shows the rate as
      "spread + текущий Rf", e.g. "5.5% = 1.5% spread + 4.0% Rf", so a
      reviewer can see the composition on screen instead of a single
      opaque percentage.
- [ ] `pytest -q` passes; `tests/golden/` REIT snapshot reviewed (expected
      to be byte-identical given `RF_RATE` doesn't change value in this
      task, only its plumbing — call out explicitly in the PR description
      if anything unexpectedly differs).

## Edge Cases Considered
- **This task does not change `RF_RATE`'s value, only where it lives.**
  Confirmed above as an explicit acceptance criterion (byte-identical
  golden snapshots) precisely because it would be easy to accidentally
  "improve" the rate while wiring it, which is not what this task is for
  — see Out of Scope.
- **A future editor changes `RF_RATE` expecting it to only affect Ordinary
  Ke.** Once this task lands, changing `RF_RATE` moves REIT cap rates too
  (by design) — the constant's doc-comment must say so explicitly, since
  today editing the Ordinary `0.04` literal has zero effect on REIT, and
  after this task it will.
- **Cap rate matrix spread could theoretically go negative if `RF_RATE`
  rises enough to make a property-type spread look too thin** — not
  possible with today's spread values (1.5%-3.0%, all positive additions
  to Rf), but if `RF_RATE` were ever raised far enough that a downstream
  consumer expected a cap rate ceiling, that's not part of this task —
  the existing `if cap_rate else 0.0` guard (`valuation.py:352`) already
  handles a zero/falsy cap rate, nothing new needed here.

## Out of Scope
- Fetching a live 10-Year Treasury yield instead of reusing the static
  constant → see [FU-04](./follow-ups.md#fu-04-live-risk-free-rate) — a
  new external data dependency and a bigger design question (it would
  also change every Ordinary/Bank Ke, not just REIT cap rates), correctly
  flagged as separate in the original backlog entry.
