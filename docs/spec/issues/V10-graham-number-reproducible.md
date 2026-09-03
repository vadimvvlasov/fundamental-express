# V10 — Make the Graham Number a real, reproducible code path (or stop putting it in reports)

## Problem
The "Число Грэма" table that appeared in `output/Screen55_Comparative_Report_2026-09-03.md`
was computed by hand in a chat session, not by this codebase — `grep -rn
"graham\|Graham" src/ financial_analyzer.py analyzers.py` returns nothing.
Running `python portfolio_analyzer.py ...` again today would not reproduce
that table at all; it would simply be absent, with no indication anything
is missing, until someone happens to compare against the earlier file by
eye.

Separately, that table used raw `BVPS = shareholders_equity / shares` —
the same goodwill-inflated quantity flagged in
[V01](./V01-tangible-equity-distress-triggers.md). For a goodwill-heavy
company (ACN was the example on hand, ~$22.5B goodwill), a Graham Number
built on raw BVPS overstates the "ceiling" price versus what Benjamin
Graham's own method — built for industrial companies with tangible
balance sheets — was designed to measure.

## Acceptance Criteria
- [ ] A real `graham_number(eps_ttm, tangible_bvps)` function exists in
      code (suggested location: a new `domain/graham.py`, or alongside
      existing per-share metrics in `domain/metrics.py` — implementer's
      choice), computing `√(22.5 × EPS_ttm × tangible_BVPS)`, where
      `tangible_bvps` uses [V01](./V01-tangible-equity-distress-triggers.md)'s
      `tangible_equity / shares`, not raw equity. **This task depends on
      V01 landing first** — it reuses that task's `tangible_equity`, it
      does not duplicate the goodwill-subtraction logic itself.
  - If V01 has not landed yet when this is picked up, that dependency
    must be re-confirmed as still accurate before starting — don't assume
    it's still true weeks or months later.
- [ ] The Graham Number and its deviation from current price
      (`(graham_number − price) / price`) are added to at least the
      Ordinary and Bank per-ticker reports, as a clearly-labeled
      "справочно, вне основной методики" section — matching the framing
      the hand-written table already used, so this is a faithful
      reproduction of the *intent*, not a new methodology decision.
- [ ] Given a fixture with known EPS, tangible BVPS, and price, the
      rendered report's Graham Number line matches a hand-computed
      expected value in a unit test (exact arithmetic check, not an
      approximation).
- [ ] Given a fixture with `eps_ttm <= 0` or `tangible_bvps <= 0` (the
      formula is undefined — a negative under the square root), the
      report shows "N/A" with a one-line reason, never a crash, never a
      fabricated/complex-number result silently coerced to something
      plausible-looking.
- [ ] `python portfolio_analyzer.py <ticker>:<shares> --allow-sample` and
      `python financial_analyzer.py <ticker> --allow-sample` both
      complete and show the new Graham Number line (or its explicit N/A)
      for sample data.
- [ ] `pytest -q` passes, with tests for: a normal fixture, the
      non-positive-input N/A case, and — since this line item is
      explicitly informational and must never influence the buy/hold/skip
      verdict — a test confirming the sins-checklist score and DCF verdict
      are unaffected by whatever the Graham Number computes to.
- [ ] `tests/golden/` snapshots updated to include the new line (expected
      to change every golden snapshot, since this is a wholly new section
      — not evidence of a bug, call it out as expected in the PR
      description).

## Edge Cases Considered
- **REIT tickers.** Graham's method assumes an industrial/tangible-asset
  balance sheet — the original hand-written table already excluded REIT
  (TRNO was flagged "минус... у REIT амортизация искажает EPS вниз ...
  формула Грэма для них методологически не подходит"). This task should
  not add a Graham Number section to REIT reports; keep it Ordinary/Bank
  only, matching that existing reasoning.
- **A company with EPS_ttm and tangible BVPS both available but a Graham
  Number wildly above or below the current price** (e.g. a fast-growing
  company Graham's method was never meant to price). No special handling
  needed beyond what's already there — the disclosure text should keep
  the existing "справочно, вне основной методики" framing so a reviewer
  doesn't mistake a wide deviation for a signal the checklist/DCF verdict
  is supposed to weight.
- **`eps_ttm` sourced from trailing-twelve-months vs. last fiscal year.**
  Confirm which `eps` series this codebase already has available
  (`financial_analyzer.py`'s `eps = find_row(df_fin, ["eps", "diluted
  eps", "basic eps"])` is annual, not TTM) and either use the latest
  annual figure with the label adjusted to say so ("EPS(FY)" not
  "EPS(ttm)"), or source a genuine TTM figure if one is already fetched
  elsewhere (`info.get("trailingEps")` is a plausible existing yfinance
  field to check) — do not label an annual figure "ttm" if that's not
  actually what's used, since the original hand-written table's own
  header claimed "ttm" without verifying which figure was actually
  behind it.

## Out of Scope
- The full classical Graham method (multi-year-averaged EPS to smooth
  cyclicality, plus the companion current-assets-vs-total-liabilities
  solvency test) — this task ships the simplified single-year formula the
  hand-written table already used, not a from-scratch reimplementation of
  Graham's full screen → see
  [FU-07](./follow-ups.md#fu-07-full-graham-method).
