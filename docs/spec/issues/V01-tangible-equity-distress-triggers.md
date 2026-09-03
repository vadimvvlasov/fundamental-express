# V01 — Use tangible equity in leverage-distress triggers, not raw (goodwill-inflated) equity

## Problem
Two places in the valuation code use `shareholders_equity` straight off the
balance sheet — which includes goodwill and other intangible assets from
past acquisitions — as the denominator of a leverage or per-share check:

1. `src/fundamental_express/domain/valuation.py:129-131`
   (`ordinary_dcf_valuation`) computes
   `debt_to_equity_ratio = latest_debt / latest_equity` and uses it, together
   with `latest_equity <= 0`, to decide whether to auto-switch a
   dividend-paying company from the classic FCF-DCF to the DDM model
   (`capital_distorted`, spec: `docs/spec/step4-ordinary-v3-implementation-spec.md`
   Section 2.3). A company whose balance sheet is genuinely distressed on a
   tangible basis, but whose goodwill happens to be large, gets a *smaller*
   D/E than reality and can silently miss the DDM switch it should get.
2. `src/fundamental_express/domain/valuation.py:267-275` (`bank_valuation`,
   ROE/P-B path) — when `roe <= 0`, fair value floors at `0.1 * bvps`, where
   `bvps = latest_equity / shares` (line 273). A bank with a goodwill-heavy
   balance sheet gets an inflated floor. (The main `bvps * (roe / Ke)`
   branch is *not* affected — `equity` cancels out algebraically there, so
   this is specifically a floor-case bug, not a general one.)

A working precedent for the correct adjustment already exists in this file:
`financial_analyzer.py:258-261` subtracts goodwill before the long-term
solvency sin check (`long_term_assets_adj = (total_assets - curr_assets) -
goodwill`). This task extends the same idea to the two spots above.

Separately: `compute_bank_metrics` (`financial_analyzer.py:401+`) does not
parse a goodwill row at all today — `goodwill` is only read inside
`compute_metrics` (Ordinary). Fixing (2) requires adding that parsing to the
bank code path first; it does not exist to reuse.

## Acceptance Criteria
- [ ] A new `tangible_equity = shareholders_equity − goodwill − other_intangibles`
      value is computed for both the Ordinary and Bank code paths (currently
      only Ordinary parses `goodwill`, and neither parses a separate
      intangibles row).
- [ ] `ordinary_dcf_valuation`'s `debt_to_equity_ratio` (and therefore
      `capital_distorted`) is computed from `tangible_equity`, not raw
      equity. Given a fixture where raw D/E ≤ 2.0 but tangible D/E > 2.0
      (dividend-paying company, large goodwill), the rendered markdown
      report's Section 3 shows the DDM warning banner (the exact text
      starting "⚠️ **Внимание:** Применена модель дисконтирования
      дивидендов (DDM)...", `sections_ordinary.py:205`) where before the
      fix it showed the plain DCF table instead.
- [ ] `bank_valuation`'s `roe <= 0` floor uses `bvps` computed from
      `tangible_equity`. Given a fixture bank with `roe <= 0` and goodwill
      > 0, the reported "Справедливая стоимость акции" is lower after the
      fix than before it, by an amount a reviewer can compute by hand as
      `0.1 * (goodwill + other_intangibles) / shares`.
- [ ] The bank report's Section 3 disclosure table
      (`sections_bank.py:38-48`, "Балансовая стоимость на акцию (BVPS)"
      row) is unchanged in the main ROE/P-B branch (not the floor) —
      confirmed by an existing or new test asserting the pre-fix and
      post-fix fair value are numerically identical for a `roe > 0`
      fixture with nonzero goodwill (this is the algebraic-cancellation
      case called out in Problem — it must stay a no-op).
- [ ] `pytest -q` passes, including at least one new test per branch above
      (Ordinary DDM-switch trigger, Bank floor value, Bank main-branch
      no-op) added to `tests/test_ordinary_v3.py` and `tests/test_bank_analyzer.py`.
- [ ] `tests/golden/` snapshots are re-run; any snapshot whose numbers
      changed is a deliberate, reviewed update (not a silent diff) — call
      out in the PR description which golden tickers changed and why.
- [ ] `python financial_analyzer.py <ticker> --allow-sample` still completes
      (sample fixture data has `Goodwill: [0, 0, 0, 0]` per
      `src/fundamental_express/data/sample.py:27`, so this must be a no-op
      on sample data — confirms the fallback path doesn't crash on an
      all-zero goodwill series).

## Edge Cases Considered
- **Goodwill row missing from yfinance for a ticker.** `find_row` already
  defaults to a `0.0`-filled series (not NaN) when a row isn't found
  (`data/parsing.py:30`, `financial_analyzer.py:164` doesn't override
  `default_val`), so `tangible_equity` falls back to raw equity with no
  NaN cascade — already handled by existing code, just needs to stay true
  once goodwill parsing is added to the Bank path too.
- **No separate "Other Intangible Assets" row.** yfinance sometimes reports
  a combined "Goodwill And Other Intangible Assets" line instead of two
  separate rows. Engineer should try the combined row first and fall back
  to goodwill-only if not found, rather than double-counting or silently
  dropping the intangibles component — exact keyword fallback order is an
  implementation detail, not specified here.
- **`tangible_equity` goes negative for a reason *other* than goodwill**
  (e.g. genuine accumulated losses on an already-tangible-heavy balance
  sheet). The existing `latest_equity <= 0` branch of `capital_distorted`
  already catches negative *raw* equity; this task must not change that
  branch's trigger condition, only the D/E ratio's denominator when raw
  equity is positive but tangible equity is not. Define
  `debt_to_equity_ratio = None` (not a divide-by-zero/negative ratio) when
  `tangible_equity <= 0`, and treat that as `capital_distorted = True` on
  its own (a company with negative tangible equity is distressed by
  definition, regardless of the D/E>2.0 threshold).
- **Bank with `roe <= 0` and *zero* goodwill.** Must be a pure no-op —
  `tangible_equity == raw equity` when goodwill/intangibles are both 0,
  so the floor value is unchanged. Covered by the sample-data acceptance
  criterion above.
- **FX-converted tickers** (e.g. a TWD-reporting ADR). `goodwill` is
  already FX-converted at `financial_analyzer.py:235`; any new
  `other_intangibles` row must be added to that same FX-conversion block,
  not left in the original currency.

## Out of Scope
- Deciding whether `tangible_equity` should also feed the Graham Number's
  BVPS if that gets implemented → see [V10](./V10-graham-number-reproducible.md),
  which explicitly depends on this task's `tangible_equity` value.
- Any data source beyond what yfinance already exposes for goodwill/
  intangibles (e.g. footnote-level intangible asset breakdowns) — not
  needed for this fix and not pursued here.
