# V08 — Clamp and disclose implausible beta values instead of passing Yahoo's raw number through

## Problem
`src/fundamental_express/data/yahoo.py:80`: `beta = info.get("beta") or
1.1` — this already has a fallback, but only for *falsy* values (`None`,
`0`, `0.0`). It does nothing for a beta that's present but implausible:
negative (a data glitch or a genuinely inverse-correlated ticker, both
worth flagging), or extremely high (>3, often a low-liquidity/small-float
stock where the regression itself is noisy). That raw number then drives
`Ke = Rf + β×ERP` directly in both `ordinary_dcf_valuation` and
`bank_valuation` (`valuation.py:32-33`, `_cost_of_equity()`), with no
visibility to the reader that the beta behind their Ke might be
unreliable.

## Acceptance Criteria
- [ ] A sanity range is applied to `beta` after the existing
      falsy-value fallback (e.g. clamp to `[-1.0, 3.0]`, or fall back to
      the existing `1.1` default entirely if outside a wider outer bound —
      exact bounds are an implementation decision, but must be documented
      in a code comment).
- [ ] When the clamp/fallback fires, `data["beta_is_fallback"]` (or
      equivalent) is set so downstream code and the report can tell "this
      is Yahoo's real number" from "this was adjusted because it looked
      broken."
- [ ] The rendered report's Ke line — currently
      `f"Ke = Rf + β×ERP = 4% + {beta:.2f}×5% = ..."` (`sections_bank.py:36`,
      and the Ordinary equivalent) — appends a visible note when the
      fallback fired (e.g. "β скорректирована с исходного X.XX — вне
      разумного диапазона"), so a reviewer sees it happened without
      digging into the calculation.
- [ ] Given a fixture with `info["beta"] = -2.0`, the report shows the
      clamped/fallback value with the disclosure note. Given
      `info["beta"] = 1.3` (a normal value), the report is byte-identical
      to today's output — no note, no clamping, pure pass-through.
- [ ] `pytest -q` passes, with tests for: negative beta, extremely high
      beta, and the untouched normal-range case.
- [ ] `tests/golden/` snapshots reviewed; any fixture ticker with an
      out-of-range beta is called out explicitly (expected to be rare or
      none, since golden fixtures are presumably hand-built with sane
      values — confirm this while implementing, don't assume).

## Edge Cases Considered
- **A ticker whose *true* beta legitimately sits outside the clamp range**
  (e.g. a triple-leveraged ETF-like instrument, or a company genuinely
  anti-correlated with the market). Clamping loses real information for
  this (rare, for a stock-picking use case) case. The disclosure note is
  the mitigation — it tells the reader a clamp happened so they can look
  up the real number themselves, rather than the report silently using an
  unreliable Ke with no signal anything was adjusted.
- **`info["beta"]` present but `NaN`** (float, not falsy in Python's
  `or`-fallback sense — `float("nan") or 1.1` evaluates to `nan`, *not*
  `1.1`, since `nan` is truthy). This is a real gap in today's existing
  fallback, not just a boundary of this task's new clamp — the clamp
  logic must explicitly check `pd.isna(beta)` in addition to the range
  bounds, or this case keeps slipping through into `Ke` as `NaN`
  regardless of this fix.
- **`--allow-sample` fixture data** (`beta: 1.1` in `data/sample.py:45`) —
  already inside any reasonable clamp range, confirms `--allow-sample`
  stays a no-op.

## Out of Scope
- Full Hamada-style unlevering/relevering against a peer group's beta
  (a materially better fix, but needs a peer-group definition this
  codebase doesn't have) → see
  [FU-05](./follow-ups.md#fu-05-peer-beta-relever).
