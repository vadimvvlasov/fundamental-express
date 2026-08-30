"""ReitAnalyzer engine tests (spec Section 4/5/7.1,
docs/spec/step3-reit-analyzer-implementation-spec.md).

Same style as tests/test_bank_analyzer.py (itself modeled on the original
tests/test_verdict_scoring.py): synthetic financials/balance/cashflow
DataFrames built directly, compute_reit_metrics() called on them - no
network access. A separate file rather than adding to
test_verdict_scoring.py (which the spec's Section 7 literally names) so
that file - and the 21 Ordinary tests it holds - never needs to change,
consistent with the hard invariant that Ordinary/Bank tests keep passing
unmodified.
"""

import pandas as pd
import pytest

from financial_analyzer import compute_reit_metrics, REIT_MAX_MINOR_SCORE

YEARS = ["2024", "2025"]


def _df(rows):
    return pd.DataFrame(rows, index=YEARS).T


def make_reit_data(
    net_income=(150.0, 150.0),
    d_and_a=(50.0, 50.0),
    gain_on_sale=(0.0, 0.0),
    capex=(-20.0, -20.0),
    rental_revenue=(300.0, 300.0),
    property_opex=(100.0, 100.0),
    re_taxes=(0.0, 0.0),
    diluted_shares=(100.0, 100.0),
    construction_in_progress=(0.0, 0.0),
    receivables=(10.0, 10.0),
    cash=(20.0, 20.0),
    total_liab=(800.0, 800.0),
    total_debt=(400.0, 400.0),
    shareholders_equity=(1000.0, 1000.0),
    dividends_paid=(-150.0, -150.0),
    price=50.0,
    shares=100.0,
    beta=1.0,
    info=None,
):
    """Flat, healthy 2-year baseline: FFO = 150+50-0 = 200, AFFO = 200-20 =
    180, NOI = 300-100-0 = 200 both years -> zero sins, DDM-style flat AFFO
    Payout well under 100%. Pass any row as a 2-tuple to override just that
    row for one test.
    """
    fin_rows = {
        "Net Income": list(net_income),
        "Total Revenue": list(rental_revenue),
        "Operating Expense": list(property_opex),
        "Diluted Average Shares": list(diluted_shares),
    }
    bal_rows = {
        "Construction In Progress": list(construction_in_progress),
        "Receivables": list(receivables),
        "Cash and Cash Equivalents": list(cash),
        "Total Liabilities Net Minority Interest": list(total_liab),
        "Total Debt": list(total_debt),
        "Stockholders Equity": list(shareholders_equity),
    }
    cf_rows = {
        "Depreciation And Amortization": list(d_and_a),
        "Capital Expenditure": list(capex),
        "Cash Dividends Paid": list(dividends_paid),
    }
    if any(v != 0.0 for v in gain_on_sale):
        cf_rows["Gain on Sale of Real Estate"] = list(gain_on_sale)
    if any(v != 0.0 for v in re_taxes):
        fin_rows["Real Estate Taxes"] = list(re_taxes)

    return {
        "ticker": "TEST",
        "financials": _df(fin_rows),
        "balance": _df(bal_rows),
        "cashflow": _df(cf_rows),
        "price": price,
        "shares": shares,
        "beta": beta,
        "fx_rate": 1.0,
        "info": info or {},
    }


def sin_ids(sins):
    return {s.id for s in sins}


# ── Section 4.1: Critical sins ──────────────────────────────────────────

def test_zero_sins_is_buy():
    m = compute_reit_metrics(make_reit_data())
    assert m.scoring.sins == []
    assert m.scoring.critical_sins == []
    assert m.scoring.minor_score == 0
    assert "КУПИТЬ" in m.scoring.verdict


def test_affo_payout_over_100_pct_is_critical():
    # AFFO = $1.00/share (100 shares -> $100 AFFO), dividends = $1.20/share
    # ($120 paid) -> payout 120% > 100% (spec Section 7.1 scenario 1).
    m = compute_reit_metrics(make_reit_data(
        net_income=(70.0, 70.0), d_and_a=(50.0, 50.0), capex=(-20.0, -20.0),  # FFO=120, AFFO=100
        dividends_paid=(-120.0, -120.0),
    ))
    assert sin_ids(m.scoring.critical_sins) == {"affo_payout_over_100"}
    assert m.affo_payout_ratio == pytest.approx(1.2)
    assert "ПРОПУСТИТЬ" in m.scoring.verdict


def test_affo_payout_at_or_below_100_pct_is_not_critical():
    m = compute_reit_metrics(make_reit_data(
        net_income=(70.0, 70.0), d_and_a=(50.0, 50.0), capex=(-20.0, -20.0),  # AFFO=100
        dividends_paid=(-100.0, -100.0),  # exactly 100%
    ))
    assert m.scoring.critical_sins == []
    assert m.affo_payout_ratio == pytest.approx(1.0)


def test_no_dividends_paid_does_not_count_affo_payout_sin():
    m = compute_reit_metrics(make_reit_data(dividends_paid=(0.0, 0.0)))
    assert m.affo_payout_ratio is None
    assert "affo_payout_over_100" not in sin_ids(m.scoring.critical_sins)


def test_occupancy_below_80_pct_is_critical():
    m = compute_reit_metrics(make_reit_data(info={"occupancy": 0.78}))
    assert sin_ids(m.scoring.critical_sins) == {"occupancy_below_80"}
    assert m.occupancy_rate == pytest.approx(0.78)
    assert "ПРОПУСТИТЬ" in m.scoring.verdict


def test_occupancy_at_80_pct_is_not_critical():
    m = compute_reit_metrics(make_reit_data(info={"occupancy": 0.80}))
    assert m.scoring.critical_sins == []


def test_occupancy_missing_defaults_to_95_pct():
    m = compute_reit_metrics(make_reit_data())
    assert m.occupancy_rate == pytest.approx(0.95)
    assert m.scoring.critical_sins == []


def test_equity_non_positive_is_critical():
    m = compute_reit_metrics(make_reit_data(shareholders_equity=(1000.0, -10.0)))
    assert sin_ids(m.scoring.critical_sins) == {"equity_negative"}
    assert "ПРОПУСТИТЬ" in m.scoring.verdict


def test_critical_sin_does_not_skip_minor_scoring():
    # Unlike Bank (Step 2), REIT critical sins do NOT interrupt minor
    # scoring (spec Section 4 has no such language) - a critical equity
    # breach alongside a real minor sin should show both.
    m = compute_reit_metrics(make_reit_data(
        shareholders_equity=(1000.0, -10.0),
        rental_revenue=(300.0, 250.0),  # NOI declines: 200 -> 150
    ))
    assert sin_ids(m.scoring.critical_sins) == {"equity_negative"}
    assert "noi_declining" in sin_ids(m.scoring.minor_sins)


# ── Section 4.2: Minor sins ──────────────────────────────────────────────

def test_affo_declining_fires():
    # capex trimmed in proportion to FFO's decline (20/200=10% -> 17/170=10%)
    # so capex_ratio_growth doesn't co-fire - isolates affo_declining alone.
    m = compute_reit_metrics(make_reit_data(net_income=(150.0, 120.0), capex=(-20.0, -17.0)))
    assert sin_ids(m.scoring.minor_sins) == {"affo_declining"}
    assert m.scoring.minor_score == pytest.approx(1.0)


def test_dilution_fires_above_2_5_pct_growth():
    m = compute_reit_metrics(make_reit_data(diluted_shares=(100.0, 103.0)))  # +3%
    assert sin_ids(m.scoring.minor_sins) == {"dilution"}
    assert m.scoring.minor_score == pytest.approx(1.0)


def test_dilution_at_2_5_pct_does_not_fire():
    m = compute_reit_metrics(make_reit_data(diluted_shares=(100.0, 102.5)))  # exactly +2.5%
    assert "dilution" not in sin_ids(m.scoring.minor_sins)


def test_buyback_bonus_floors_score_at_zero():
    m = compute_reit_metrics(make_reit_data(diluted_shares=(100.0, 98.0)))  # -2%
    assert sin_ids(m.scoring.minor_sins) == {"buyback_bonus"}
    assert m.scoring.minor_score == 0.0


def test_high_leverage_above_200_pct_fires():
    m = compute_reit_metrics(make_reit_data(total_debt=(400.0, 2100.0)))  # D/E 2.1x
    assert m.debt_to_equity == pytest.approx(2.1)
    assert sin_ids(m.scoring.minor_sins) == {"high_leverage"}
    assert m.scoring.minor_score == pytest.approx(0.5)


def test_high_leverage_at_200_pct_does_not_fire():
    m = compute_reit_metrics(make_reit_data(total_debt=(400.0, 2000.0)))  # exactly 2.0x
    assert "high_leverage" not in sin_ids(m.scoring.minor_sins)


def test_noi_declining_fires():
    m = compute_reit_metrics(make_reit_data(rental_revenue=(300.0, 280.0)))  # NOI 200 -> 180
    assert sin_ids(m.scoring.minor_sins) == {"noi_declining"}
    assert m.scoring.minor_score == pytest.approx(0.5)


def test_capex_ratio_growth_above_5_pct_fires():
    # CapEx/FFO: 20/200=10% -> 40/220=~18.2% (FFO also shifts with D&A held
    # flat and capex change alone) - use a clean isolated bump instead.
    m = compute_reit_metrics(make_reit_data(capex=(-20.0, -30.0)))  # ratio 10% -> 15%, FFO unchanged (capex doesn't feed FFO)
    assert sin_ids(m.scoring.minor_sins) == {"capex_ratio_growth", "affo_declining"}
    assert m.scoring.minor_score == pytest.approx(1.3)


def test_max_minor_score_matches_weight_table():
    # 1.0x3 (affo/occupancy/dilution) + 0.5x2 (leverage/noi) + 0.3 (capex ratio) = 4.3
    assert REIT_MAX_MINOR_SCORE == pytest.approx(4.3)


# ── Section 4.3: Verdict scale boundaries ────────────────────────────────

def test_minor_score_exactly_1_0_is_buy_boundary_inclusive():
    m = compute_reit_metrics(make_reit_data(total_debt=(400.0, 2100.0), rental_revenue=(300.0, 280.0)))
    # high_leverage (0.5) + noi_declining (0.5) = 1.0
    assert m.scoring.minor_score == pytest.approx(1.0)
    assert "КУПИТЬ" in m.scoring.verdict


def test_minor_score_3_0_is_skip():
    m = compute_reit_metrics(make_reit_data(
        net_income=(150.0, 120.0), capex=(-20.0, -17.0),  # affo_declining: +1.0 (capex ratio held flat)
        diluted_shares=(100.0, 103.0),  # dilution: +1.0
        total_debt=(400.0, 2100.0),     # high_leverage: +0.5
        rental_revenue=(300.0, 280.0),  # noi_declining: +0.5
    ))
    assert m.scoring.critical_sins == []
    assert sin_ids(m.scoring.minor_sins) == {"affo_declining", "dilution", "high_leverage", "noi_declining"}
    assert m.scoring.minor_score == pytest.approx(3.0)
    assert "ПРОПУСТИТЬ" in m.scoring.verdict


# ── Section 5/7.1: NAV valuation bridge ──────────────────────────────────

def test_nav_bridge_matches_spec_worked_example():
    # spec Section 7.1 scenario 3: NOI=$100M, Cap Rate=5.0%, Cash=$10M,
    # Liabilities=$500M, Shares=10M -> Property Value=$2000M,
    # NAV=$2000M+$10M-$500M=$1510M, Fair Price=$151.00.
    m = compute_reit_metrics(make_reit_data(
        rental_revenue=(300.0, 400.0), property_opex=(100.0, 300.0),  # NOI = 100
        cash=(20.0, 10.0), receivables=(10.0, 0.0), construction_in_progress=(0.0, 0.0),
        total_liab=(800.0, 500.0),
        shares=10.0,
        info={"capRate": 0.05},
    ))
    assert m.cap_rate == pytest.approx(0.05)
    assert m.cap_rate_label == "Explicit (info.capRate)"
    assert m.property_value == pytest.approx(2000.0)
    assert m.nav == pytest.approx(1510.0)
    assert m.valuation.fair_value_share == pytest.approx(151.00, abs=0.01)


def test_cap_rate_matrix_by_industry_keyword():
    assert compute_reit_metrics(make_reit_data(info={"industry": "REIT - Industrial"})).cap_rate == pytest.approx(0.055)
    assert compute_reit_metrics(make_reit_data(info={"industry": "REIT - Residential"})).cap_rate == pytest.approx(0.060)
    assert compute_reit_metrics(make_reit_data(info={"industry": "REIT - Healthcare"})).cap_rate == pytest.approx(0.065)
    assert compute_reit_metrics(make_reit_data(info={"industry": "REIT - Retail"})).cap_rate == pytest.approx(0.070)
    assert compute_reit_metrics(make_reit_data(info={"industry": "REIT - Diversified"})).cap_rate == pytest.approx(0.065)


# ── Section 7.1 scenario 4: native routing without --force ──────────────

def test_analyzer_factory_routes_reit_without_force_or_exception():
    import argparse
    from analyzers import AnalyzerFactory, ReitAnalyzer

    args = argparse.Namespace(retries=1, retry_delay=1, allow_sample=False, force=False, required_return=None)
    analyzer = AnalyzerFactory.get_analyzer("O", args, {"sector": "Real Estate", "industry": "REIT - Retail"})
    assert isinstance(analyzer, ReitAnalyzer)
    assert args.excluded_sector is None


def test_analyzer_factory_routes_bank_before_reit_check():
    import argparse
    from analyzers import AnalyzerFactory, BankAnalyzer

    args = argparse.Namespace(retries=1, retry_delay=1, allow_sample=False, force=False, required_return=None)
    analyzer = AnalyzerFactory.get_analyzer("JPM", args, {"sector": "Financial Services", "industry": "Banks - Diversified"})
    assert isinstance(analyzer, BankAnalyzer)
