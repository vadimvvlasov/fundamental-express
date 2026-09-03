# Valuation-objectivity issues (groomed)

Source material: `docs/spec/valuation-objectivity-backlog.md` (V01-V10, filed
as terse dev-facing notes). Each one below has been rewritten against
`_docs/task-template.md` — Problem / Acceptance Criteria / Edge Cases
Considered / Out of Scope — grounded in the current code (line numbers,
actual field names, existing tests), not just the original one-paragraph
description. No code was changed while grooming these; some issues correct
a factual assumption the original backlog entry made (noted inline where
that happens — see V06, V07, V09).

| # | Title | Depends on |
|---|---|---|
| [V01](./V01-tangible-equity-distress-triggers.md) | Tangible equity in leverage-distress triggers | — |
| [V02](./V02-regression-cagr.md) | Multi-year regression CAGR, not endpoint-to-endpoint | — |
| [V03](./V03-normalize-nonrecurring-items.md) | Strip explicit non-recurring items from FCF/Net Income | — |
| [V04](./V04-lease-adjusted-net-debt.md) | Lease-inclusive fair value as headline for lease-heavy sectors | — |
| [V05](./V05-implied-cost-of-debt.md) | Cost of debt from the company's own interest expense | — |
| [V06](./V06-reit-cap-rate-rate-regime.md) | REIT cap rate tied to the risk-free rate | — |
| [V07](./V07-reit-trailing-average.md) | Trailing multi-year average NOI for REIT NAV | — |
| [V08](./V08-beta-sanity-check.md) | Clamp and disclose implausible beta | — |
| [V09](./V09-sector-terminal-growth.md) | Sector-bucketed terminal growth | — |
| [V10](./V10-graham-number-reproducible.md) | Graham Number as a real, reproducible code path | **V01** |

[`follow-ups.md`](./follow-ups.md) — FU-01 through FU-08, everything an
issue above explicitly pushed out of scope. Filed, not yet groomed.

## Order of execution (suggested, not mandated)
V01 and V02 touch the same three `valuation.py` functions the most and are
cheapest — do those first, in either order, before V10 (which depends on
V01's `tangible_equity`). V06 and V09 both fix the same kind of bug found
while grooming (a hardcoded literal duplicated across two functions instead
of a shared constant) — worth doing back-to-back so the same refactor
pattern isn't re-derived twice. Everything else is independent.
