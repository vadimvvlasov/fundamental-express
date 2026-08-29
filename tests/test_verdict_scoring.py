"""Verdict scoring engine tests (spec Section 1.6, docs/spec/technical-implementation-spec.md).

Builds minimal synthetic financials/balance/cashflow DataFrames directly (same
shape as financial_analyzer._sample_data()) and calls compute_metrics() on
them - no network access, no yfinance involved. Every test starts from a
flat, healthy 2-year baseline where nothing declines and nothing is critical,
then overrides only the rows needed to isolate the sin(s) under test.
"""

import pandas as pd
import pytest

from financial_analyzer import compute_metrics, MAX_MINOR_SCORE

YEARS = ["2023", "2024"]


def _df(rows):
    return pd.DataFrame(rows, index=YEARS).T


def make_data(
    revenue=(1000.0, 1000.0),
    operating_income=(200.0, 200.0),
    net_income=(150.0, 150.0),
    eps=(2.0, 2.0),
    cost_of_revenue=(600.0, 600.0),
    curr_assets=(500.0, 500.0),
    curr_liab=(200.0, 200.0),
    total_assets=(2000.0, 2000.0),
    total_liab=(800.0, 800.0),
    goodwill=(0.0, 0.0),
    equity=(1200.0, 1200.0),
    long_term_debt=(100.0, 100.0),
    cash=(300.0, 300.0),
    fcf=(180.0, 180.0),
):
    """Flat, healthy baseline by default - zero sins, verdict BUY. Pass any
    row as a 2-tuple (2023, 2024) to override just that row for one test."""
    financials = _df({
        "Total Revenue": list(revenue),
        "Operating Income": list(operating_income),
        "Net Income": list(net_income),
        "Diluted EPS": list(eps),
        "Cost Of Revenue": list(cost_of_revenue),
    })
    balance = _df({
        "Total Current Assets": list(curr_assets),
        "Total Current Liabilities": list(curr_liab),
        "Total Assets": list(total_assets),
        "Total Liabilities Net Minority Interest": list(total_liab),
        "Goodwill": list(goodwill),
        "Stockholders Equity": list(equity),
        "Long Term Debt": list(long_term_debt),
        "Cash And Cash Equivalents": list(cash),
    })
    cashflow = _df({"Free Cash Flow": list(fcf)})
    return {
        "financials": financials,
        "balance": balance,
        "cashflow": cashflow,
        "price": 50.0,
        "shares": 100.0,
        "beta": 1.0,
    }


def sin_ids(sins):
    return {s.id for s in sins}


def test_zero_sins_is_buy():
    m = compute_metrics(make_data())
    assert m["sins"] == []
    assert m["critical_sins"] == []
    assert m["minor_score"] == 0
    assert m["verdict_color_key"] == "success"
    assert "КУПИТЬ" in m["verdict"]


def test_single_critical_sin_forces_skip_even_with_zero_minor_score():
    m = compute_metrics(make_data(fcf=(180.0, -10.0)))
    assert sin_ids(m["critical_sins"]) == {"fcf_negative"}
    assert m["minor_sins"] == []
    assert m["minor_score"] == 0
    assert m["verdict_color_key"] == "danger"
    assert "ПРОПУСТИТЬ" in m["verdict"]


def test_minor_score_exactly_1_0_is_buy_boundary_inclusive():
    m = compute_metrics(make_data(equity=(1200.0, 1100.0)))
    assert m["critical_sins"] == []
    assert sin_ids(m["minor_sins"]) == {"equity_declining"}
    assert m["minor_score"] == pytest.approx(1.0)
    assert m["verdict_color_key"] == "success"
    assert "КУПИТЬ" in m["verdict"]


def test_minor_score_1_1_is_watch():
    m = compute_metrics(make_data(
        cost_of_revenue=(600.0, 650.0),   # gross margin 40% -> 35%: +0.5
        net_income=(150.0, 140.0),        # net income decline: +0.3, net margin 15%->14%: +0.3
    ))
    assert m["critical_sins"] == []
    assert sin_ids(m["minor_sins"]) == {
        "gross_margin_declining", "net_income_declining", "net_margin_declining",
    }
    assert m["minor_score"] == pytest.approx(1.1)
    assert m["verdict_color_key"] == "warning"
    assert "НАБЛЮДАТЬ" in m["verdict"]


def test_minor_score_exactly_2_5_is_watch_boundary_inclusive():
    m = compute_metrics(make_data(
        equity=(1200.0, 1100.0),          # +1.0
        fcf=(180.0, 150.0),               # stays positive, declining: +1.0
        curr_assets=(540.0, 450.0),       # CR 1.8 -> 1.5, still < 2.0: +0.5
        curr_liab=(300.0, 300.0),
    ))
    assert m["critical_sins"] == []
    assert sin_ids(m["minor_sins"]) == {"equity_declining", "fcf_declining", "cr_declining"}
    assert m["minor_score"] == pytest.approx(2.5)
    assert m["verdict_color_key"] == "warning"
    assert "НАБЛЮДАТЬ" in m["verdict"]


def test_minor_score_2_6_is_skip():
    m = compute_metrics(make_data(
        equity=(1200.0, 1100.0),   # +1.0
        fcf=(180.0, 150.0),        # +1.0
        net_income=(150.0, 140.0), # +0.3, net margin +0.3
    ))
    assert m["critical_sins"] == []
    assert sin_ids(m["minor_sins"]) == {
        "equity_declining", "fcf_declining", "net_income_declining", "net_margin_declining",
    }
    assert m["minor_score"] == pytest.approx(2.6)
    assert m["verdict_color_key"] == "danger"
    assert "ПРОПУСТИТЬ" in m["verdict"]


def test_cr_below_1_is_critical_and_does_not_also_fire_cr_declining():
    m = compute_metrics(make_data(
        curr_assets=(400.0, 270.0),  # CR 1.33 -> 0.9
        curr_liab=(300.0, 300.0),
    ))
    assert m["current_ratio"] == pytest.approx(0.9)
    assert sin_ids(m["critical_sins"]) == {"cr_below_1"}
    assert "cr_declining" not in sin_ids(m["minor_sins"])
    assert "ПРОПУСТИТЬ" in m["verdict"]


def test_cr_1_5_declining_from_1_8_is_minor_only():
    m = compute_metrics(make_data(
        curr_assets=(540.0, 450.0),  # CR 1.8 -> 1.5
        curr_liab=(300.0, 300.0),
    ))
    assert m["current_ratio"] == pytest.approx(1.5)
    assert m["critical_sins"] == []
    assert sin_ids(m["minor_sins"]) == {"cr_declining"}


def test_cr_2_5_declining_from_3_0_fires_no_sin():
    m = compute_metrics(make_data(
        curr_assets=(600.0, 500.0),  # CR 3.0 -> 2.5, healthy-decline carve-out
        curr_liab=(200.0, 200.0),
    ))
    assert m["current_ratio"] == pytest.approx(2.5)
    assert m["sins"] == []


def test_max_minor_score_matches_weight_table():
    assert MAX_MINOR_SCORE == pytest.approx(6.1)
