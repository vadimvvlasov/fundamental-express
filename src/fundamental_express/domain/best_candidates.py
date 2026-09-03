""""Лучшие кандидаты" selection for the portfolio comparative report.

Was a one-off table hand-built in a chat session for every portfolio run
(same gap V10's Graham Number had before it got a real code path) - this
makes the selection reproducible and puts it in the report itself instead
of requiring a human to re-derive it by eye each time.

Selection rule: every ticker with `verdict_color_key == "success"` (0
critical sins + BUY per the sins-checklist score - see
`domain/sins.py::score()`, the `elif minor_score_value <= BUY_THRESHOLD`
branch, only reachable when critical_sins is already empty) - Ordinary,
Bank, and REIT together, sorted by |DCF/DDM/NAV deviation| descending. No
cap - every qualifying ticker is shown (an earlier version capped this at
a top-8 subset and split Ordinary out into its own separate callout; both
of those turned out to work against what a reader actually wants from
this table - see the ticket/chat history for why they were dropped).

A single caveat applies across the whole table rather than per-row: an
Ordinary DCF deviation and a Bank DDM/ROE-P-B deviation aren't the same
kind of number (different models, different meaning of "how far from fair
value"), so the sign/magnitude isn't directly comparable across kinds even
though they're ranked in one list - the `_type_label()` column in the
renderer is what keeps that visible at a glance, and the narrative text
spells it out once instead of per row.
"""


def _kind(m):
    return getattr(m, "kind", "ordinary")


def select_best_candidates(results):
    """Returns a dict: candidates (list of result dicts, every kind,
    ranked by |over_under_pct| descending, no cap), bank_count (int,
    Bank-kind entries in `candidates`), best_reit (the highest-ranked
    REIT entry in `candidates`, or None), negative_fair_value (list of
    result dicts, Ordinary-kind, fair_value_share < 0, from the FULL
    result set, regardless of verdict - a real DCF artifact worth naming,
    not a "candidate")."""
    ok_results = [r for r in results if r.get("ok")]
    buys = [r for r in ok_results if r["metrics"].scoring.verdict_color_key == "success"]
    candidates = sorted(buys, key=lambda r: abs(r["metrics"].valuation.over_under_pct), reverse=True)

    bank_count = sum(1 for r in candidates if _kind(r["metrics"]) == "bank")
    best_reit = next((r for r in candidates if _kind(r["metrics"]) == "reit"), None)

    negative_fair_value = [
        r for r in ok_results
        if _kind(r["metrics"]) == "ordinary" and r["metrics"].valuation.fair_value_share < 0
    ]

    return {
        "candidates": candidates,
        "bank_count": bank_count,
        "best_reit": best_reit,
        "negative_fair_value": negative_fair_value,
    }
