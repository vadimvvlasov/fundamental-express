"""Best Candidates selection for the portfolio comparative report - was a
one-off hand-built table per portfolio run before this
(domain/best_candidates.py::select_best_candidates), now a real,
reproducible rule: every 0-crit/BUY ticker, no cap, ranked by
|deviation|, Ordinary/Bank/REIT together.
"""

import pytest

from financial_analyzer import compute_bank_metrics, compute_metrics, compute_reit_metrics
from fundamental_express.domain.best_candidates import select_best_candidates
from tests.test_bank_analyzer import make_bank_data
from tests.test_ordinary_v3 import make_data
from tests.test_reit_analyzer import make_reit_data


def _r(ticker, metrics, weight=1):
    return {"ticker": ticker, "weight": weight, "ok": True, "metrics": metrics}


def _buy_bank(price):
    # ROE/P-B path (no dividends), zero sins baseline - always BUY.
    return compute_bank_metrics(make_bank_data(cash_dividends_paid=None, dividend_yield=0.0, price=price))


def _buy_reit(price):
    return compute_reit_metrics(make_reit_data(price=price))


def test_ranks_all_kinds_together_by_deviation_magnitude_descending():
    # ROE/P-B fair value doesn't depend on price at all (bvps*(roe/Ke), all
    # from the balance sheet/income statement) - it's fixed by the fixture
    # at ~16.67 here. |over_under_pct| = |fair - price| / price, so moving
    # price further from that fixed fair value is what grows |deviation|.
    results = [
        _r("A", _buy_bank(price=16.0)),   # closest to fair value -> smallest |deviation|
        _r("B", _buy_bank(price=200.0)),  # furthest -> biggest |deviation|
        _r("C", _buy_bank(price=33.0)),   # middle
    ]
    selection = select_best_candidates(results)
    tickers = [r["ticker"] for r in selection["candidates"]]
    assert tickers == ["B", "C", "A"]


def test_no_cap_all_qualifying_tickers_included():
    results = [_r(f"T{i}", _buy_bank(price=10.0 + i)) for i in range(12)]
    selection = select_best_candidates(results)
    assert len(selection["candidates"]) == 12


def test_ordinary_included_in_the_same_list_as_bank_reit():
    ordinary_buy = compute_metrics(make_data())
    assert ordinary_buy.scoring.verdict_color_key == "success"
    results = [_r("ORD", ordinary_buy), _r("BANK", _buy_bank(price=45.0))]
    selection = select_best_candidates(results)
    tickers = {r["ticker"] for r in selection["candidates"]}
    assert tickers == {"ORD", "BANK"}


def test_best_reit_is_the_highest_ranked_reit_entry():
    results = [_r("BANK", _buy_bank(price=45.0)), _r("REIT1", _buy_reit(price=45.0))]
    selection = select_best_candidates(results)
    assert selection["best_reit"]["ticker"] == "REIT1"


def test_best_reit_none_when_no_reit_qualifies():
    results = [_r("BANK", _buy_bank(price=45.0))]
    selection = select_best_candidates(results)
    assert selection["best_reit"] is None


def test_bank_count_counts_every_qualifying_bank_no_cap():
    results = [_r(f"B{i}", _buy_bank(price=10.0 + i)) for i in range(5)]
    selection = select_best_candidates(results)
    assert selection["bank_count"] == 5


def test_negative_fair_value_flags_ordinary_only_regardless_of_verdict():
    # Crushing debt relative to a tiny FCF stream -> negative equity value
    # -> negative fair_value_share. Verdict doesn't matter for this list.
    heavy_debt = compute_metrics(make_data(long_term_debt=(50000.0, 50000.0, 50000.0, 50000.0)))
    assert heavy_debt.valuation.fair_value_share < 0
    healthy_bank = _buy_bank(price=45.0)
    results = [_r("HEAVY", heavy_debt), _r("BANK", healthy_bank)]
    selection = select_best_candidates(results)
    assert [r["ticker"] for r in selection["negative_fair_value"]] == ["HEAVY"]


def test_negative_fair_value_never_flags_bank_or_reit():
    # Bank ROE/P-B floor (0.1 * bvps) and REIT NAV can't go negative the
    # same way an Ordinary DCF can - this list is Ordinary-only by design.
    results = [_r("BANK", _buy_bank(price=45.0)), _r("REIT1", _buy_reit(price=45.0))]
    selection = select_best_candidates(results)
    assert selection["negative_fair_value"] == []


def test_not_ok_results_are_excluded_entirely():
    results = [
        {"ticker": "BAD", "weight": 1, "ok": False, "error": "no data"},
        _r("BANK", _buy_bank(price=45.0)),
    ]
    selection = select_best_candidates(results)
    assert len(selection["candidates"]) == 1
    assert selection["negative_fair_value"] == []


def test_non_buy_verdicts_never_appear_in_candidates():
    # A ticker with a critical sin (SKIP verdict) must never rank, even
    # with an enormous deviation.
    skip_bank = compute_bank_metrics(make_bank_data(
        cash_dividends_paid=None, dividend_yield=0.0,
        net_interest_income=(-10.0, -10.0, -10.0, -10.0),  # critical: nii_non_positive
        price=1.0,
    ))
    assert skip_bank.scoring.verdict_color_key == "danger"
    results = [_r("SKIPPED", skip_bank), _r("BANK", _buy_bank(price=45.0))]
    selection = select_best_candidates(results)
    assert [r["ticker"] for r in selection["candidates"]] == ["BANK"]
