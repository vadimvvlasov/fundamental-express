"""Verdict scoring engine tests (spec Section 1.6, docs/spec/technical-implementation-spec.md).

Builds minimal synthetic financials/balance/cashflow DataFrames directly (same
shape as financial_analyzer._sample_data()) and calls compute_metrics() on
them - no network access, no yfinance involved. Every test starts from a
flat, healthy 2-year baseline where nothing declines and nothing is critical,
then overrides only the rows needed to isolate the sin(s) under test.
"""

import pandas as pd
import pytest

from financial_analyzer import compute_metrics, required_return_type, MAX_MINOR_SCORE

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
    diluted_shares=None,
    current_debt=None,
):
    """Flat, healthy baseline by default - zero sins, verdict BUY. Pass any
    row as a 2-tuple (2023, 2024) to override just that row for one test.

    diluted_shares/current_debt default to None (row omitted entirely, not
    just flat) so find_row()'s NaN default kicks in exactly as it would for
    a real ticker missing that statement line - this is what keeps every
    pre-existing test in this file passing unmodified: dilution/buyback and
    the CR smart-bypass are all silently skipped unless a test opts in.
    """
    fin_rows = {
        "Total Revenue": list(revenue),
        "Operating Income": list(operating_income),
        "Net Income": list(net_income),
        "Diluted EPS": list(eps),
        "Cost Of Revenue": list(cost_of_revenue),
    }
    if diluted_shares is not None:
        fin_rows["Diluted Average Shares"] = list(diluted_shares)
    bal_rows = {
        "Total Current Assets": list(curr_assets),
        "Total Current Liabilities": list(curr_liab),
        "Total Assets": list(total_assets),
        "Total Liabilities Net Minority Interest": list(total_liab),
        "Goodwill": list(goodwill),
        "Stockholders Equity": list(equity),
        "Long Term Debt": list(long_term_debt),
        "Cash And Cash Equivalents": list(cash),
    }
    if current_debt is not None:
        bal_rows["Current Debt"] = list(current_debt)
    financials = _df(fin_rows)
    balance = _df(bal_rows)
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
    # 6 x 1.0 (equity/fcf/revenue/op_income/dilution/cr_below_1_bypassed)
    # + 3 x 0.5 (cr_declining/gross_margin/operating_margin) + 2 x 0.3 (net_income/net_margin) = 8.1
    assert MAX_MINOR_SCORE == pytest.approx(8.1)


# ── Step 1: Dilution / Buyback bonus (spec Section 2.2) ─────────────────

def test_dilution_fires_above_1_5_pct_growth():
    m = compute_metrics(make_data(diluted_shares=(100.0, 102.0)))  # +2.0%
    assert sin_ids(m["minor_sins"]) == {"dilution"}
    assert m["minor_score"] == pytest.approx(1.0)
    assert "КУПИТЬ" in m["verdict"]


def test_buyback_bonus_alone_floors_at_zero_not_negative():
    m = compute_metrics(make_data(diluted_shares=(100.0, 98.0)))  # -2.0%, well past the 1/1.015 threshold
    assert sin_ids(m["minor_sins"]) == {"buyback_bonus"}
    assert m["minor_score"] == 0.0  # max(0.0, -0.5) - never negative
    assert "КУПИТЬ" in m["verdict"]


def test_buyback_bonus_reduces_a_combined_score():
    m = compute_metrics(make_data(
        equity=(1200.0, 1100.0),          # +1.0
        diluted_shares=(100.0, 98.0),     # -0.5 bonus
    ))
    assert sin_ids(m["minor_sins"]) == {"equity_declining", "buyback_bonus"}
    assert m["minor_score"] == pytest.approx(0.5)


# ── Step 1: Current Ratio < 1.0 smart bypass (spec Section 2.3) ─────────

def test_cr_below_1_bypassed_when_fcf_positive_and_cash_covers_current_debt():
    m = compute_metrics(make_data(
        curr_assets=(400.0, 270.0), curr_liab=(300.0, 300.0),  # CR 1.33 -> 0.9
        current_debt=(50.0, 50.0),  # cash (300, baseline) > current_debt (50)
    ))
    assert m["current_ratio"] == pytest.approx(0.9)
    assert m["critical_sins"] == []
    assert sin_ids(m["minor_sins"]) == {"cr_below_1_bypassed"}
    assert m["minor_score"] == pytest.approx(1.0)
    assert "КУПИТЬ" in m["verdict"]  # NOT an automatic SKIP


def test_cr_below_1_stays_critical_when_current_debt_row_is_missing():
    # Same CR/FCF/cash as the bypass test above, but current_debt omitted
    # (NaN) - leniency must never be granted on missing data.
    m = compute_metrics(make_data(
        curr_assets=(400.0, 270.0), curr_liab=(300.0, 300.0),
    ))
    assert sin_ids(m["critical_sins"]) == {"cr_below_1"}
    assert "cr_below_1_bypassed" not in sin_ids(m["minor_sins"])
    assert "ПРОПУСТИТЬ" in m["verdict"]


def test_cr_below_1_not_bypassed_when_fcf_negative():
    m = compute_metrics(make_data(
        curr_assets=(400.0, 270.0), curr_liab=(300.0, 300.0),  # CR 0.9
        current_debt=(50.0, 50.0),  # cash would cover current_debt...
        fcf=(180.0, -10.0),         # ...but FCF is negative, so bypass is not eligible
    ))
    assert sin_ids(m["critical_sins"]) == {"cr_below_1", "fcf_negative"}
    assert "cr_below_1_bypassed" not in sin_ids(m["minor_sins"])


# ── Step 1: --required-return (spec Sections 2.4/2.5) ────────────────────

def test_required_return_overrides_capm_cost_of_equity():
    m_default = compute_metrics(make_data())
    assert m_default["required_return_used"] is False
    assert m_default["cost_of_equity"] == pytest.approx(0.09)  # beta=1.0: 4% + 1.0*5%

    m_override = compute_metrics(make_data(), required_return=0.12)
    assert m_override["required_return_used"] is True
    assert m_override["cost_of_equity"] == pytest.approx(0.12)


def test_required_return_type_accepts_valid_decimal():
    assert required_return_type("0.12") == pytest.approx(0.12)


def test_required_return_type_rejects_percent_typo_with_helpful_message():
    import argparse
    with pytest.raises(argparse.ArgumentTypeError, match=r"0\.150"):
        required_return_type("15")


def test_required_return_type_rejects_below_range():
    import argparse
    with pytest.raises(argparse.ArgumentTypeError):
        required_return_type("0.03")


def test_required_return_type_rejects_above_range_but_below_1():
    import argparse
    with pytest.raises(argparse.ArgumentTypeError):
        required_return_type("0.5")
