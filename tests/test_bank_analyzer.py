"""BankAnalyzer engine tests (spec Section 4/5, docs/spec/step2-bank-analyzer-implementation-spec.md).

Same style as tests/test_verdict_scoring.py: synthetic financials/balance/
cashflow DataFrames built directly, compute_bank_metrics() called on them -
no network access. A flat, healthy 4-year baseline (zero sins, DDM path)
by default; each test overrides only the rows needed to isolate the
sin/model under test.

Covers the checklist's "problem bank" case (spec Section 7 item 2, SIVBQ or
equivalent) synthetically - delisted tickers like SIVBQ have no data left in
yfinance to fetch live (verified during Step 2 testing), so a negative-ROE/
negative-NII bank is constructed here instead.
"""

import pandas as pd
import pytest

from financial_analyzer import compute_bank_metrics, BANK_MAX_MINOR_SCORE

YEARS = ["2022", "2023", "2024", "2025"]


def _df(rows):
    return pd.DataFrame(rows, index=YEARS).T


def make_bank_data(
    interest_income=(500.0, 500.0, 500.0, 500.0),
    interest_expense=(150.0, 150.0, 150.0, 150.0),
    net_interest_income=None,
    commissions_income=(80.0, 80.0, 80.0, 80.0),
    trading_income=(20.0, 20.0, 20.0, 20.0),
    credit_loss_provision=(30.0, 30.0, 30.0, 30.0),
    non_interest_expense=(200.0, 200.0, 200.0, 200.0),
    net_income=(150.0, 150.0, 150.0, 150.0),
    preferred_dividends=(0.0, 0.0, 0.0, 0.0),
    diluted_shares=(100.0, 100.0, 100.0, 100.0),
    cash_and_equiv=(300.0, 300.0, 300.0, 300.0),
    net_loans=(2000.0, 2000.0, 2000.0, 2000.0),
    total_deposits=(2500.0, 2500.0, 2500.0, 2500.0),
    total_borrowings=(400.0, 400.0, 400.0, 400.0),
    shareholders_equity=(1000.0, 1000.0, 1000.0, 1000.0),
    goodwill=(0.0, 0.0, 0.0, 0.0),
    cash_dividends_paid=(-50.0, -50.0, -50.0, -50.0),
    price=50.0,
    shares=100.0,
    beta=1.0,
    dividend_yield=0.02,
):
    """Flat, healthy baseline: zero sins, DDM path (pays_dividends=True via
    cash_dividends_paid > 0), verdict BUY. Pass any row as a 4-tuple to
    override just that row for one test; pass cash_dividends_paid=None (or
    all-zero) plus dividend_yield=0 to force the ROE/P-B path instead.
    """
    fin_rows = {
        "Interest Income": list(interest_income),
        "Interest Expense": list(interest_expense),
        "Fees and Commissions": list(commissions_income),
        "Trading Revenue": list(trading_income),
        "Provision for Credit Losses": list(credit_loss_provision),
        "Non Interest Expense": list(non_interest_expense),
        "Net Income": list(net_income),
        "Preferred Stock Dividends": list(preferred_dividends),
        "Diluted Average Shares": list(diluted_shares),
    }
    if net_interest_income is not None:
        fin_rows["Net Interest Income"] = list(net_interest_income)
    bal_rows = {
        "Cash and Cash Equivalents": list(cash_and_equiv),
        "Net Loans": list(net_loans),
        "Total Deposits": list(total_deposits),
        "Long Term Debt": list(total_borrowings),
        "Stockholders Equity": list(shareholders_equity),
        "Goodwill": list(goodwill),
    }
    cf_rows = {}
    if cash_dividends_paid is not None:
        cf_rows["Cash Dividends Paid"] = list(cash_dividends_paid)
    else:
        cf_rows["Cash Dividends Paid"] = [0.0] * len(YEARS)

    return {
        "financials": _df(fin_rows),
        "balance": _df(bal_rows),
        "cashflow": _df(cf_rows),
        "price": price,
        "shares": shares,
        "beta": beta,
        "fx_rate": 1.0,
        "info": {"dividendYield": dividend_yield},
    }


def sin_ids(sins):
    return {s.id for s in sins}


# ── Section 4.1: Critical sins ──────────────────────────────────────────

def test_zero_sins_is_buy_and_ddm_selected():
    m = compute_bank_metrics(make_bank_data())
    assert m.scoring.sins == []
    assert m.scoring.critical_sins == []
    assert m.scoring.minor_score == 0
    assert "КУПИТЬ" in m.scoring.verdict
    assert m.valuation.valuation_model == "DDM"


def test_nii_non_positive_is_critical_and_skips_minor_scoring():
    # interest_expense >= interest_income in the latest year -> NII <= 0.
    m = compute_bank_metrics(make_bank_data(
        interest_income=(500.0, 500.0, 500.0, 500.0),
        interest_expense=(150.0, 150.0, 150.0, 520.0),
    ))
    assert sin_ids(m.scoring.critical_sins) == {"nii_non_positive"}
    assert m.scoring.minor_sins == []  # detailed minor scoring interrupted (spec 4.1)
    assert m.scoring.minor_score == 0
    assert "ПРОПУСТИТЬ" in m.scoring.verdict


def test_equity_non_positive_is_critical():
    m = compute_bank_metrics(make_bank_data(
        shareholders_equity=(1000.0, 1000.0, 1000.0, -50.0),
    ))
    assert sin_ids(m.scoring.critical_sins) == {"equity_negative"}
    assert m.scoring.minor_sins == []
    assert "ПРОПУСТИТЬ" in m.scoring.verdict


# ── Section 5: Valuation model selection ────────────────────────────────

def test_roe_pb_model_selected_when_no_dividends():
    m = compute_bank_metrics(make_bank_data(cash_dividends_paid=None, dividend_yield=0.0))
    assert m.valuation.valuation_model == "ROE_PB"
    assert m.bvps == pytest.approx(1000.0 / 100.0)
    assert m.roe == pytest.approx(150.0 / 1000.0)


def test_roe_pb_liquidation_discount_when_roe_non_positive():
    m = compute_bank_metrics(make_bank_data(
        cash_dividends_paid=None, dividend_yield=0.0,
        net_income=(150.0, 150.0, 150.0, -20.0),
    ))
    assert m.valuation.valuation_model == "ROE_PB"
    assert m.roe <= 0
    bvps = 1000.0 / 100.0
    assert m.valuation.fair_value_share == pytest.approx(0.1 * bvps)


# ── V01: tangible equity (goodwill-adjusted) drives the roe<=0 floor ────

def test_roe_pb_liquidation_discount_uses_tangible_bvps_not_raw():
    # Raw bvps = 1000/100 = 10.0; tangible bvps = (1000-400)/100 = 6.0.
    # Floor must use the tangible figure, not the goodwill-inflated raw one.
    m = compute_bank_metrics(make_bank_data(
        cash_dividends_paid=None, dividend_yield=0.0,
        net_income=(150.0, 150.0, 150.0, -20.0),
        goodwill=(400.0, 400.0, 400.0, 400.0),
    ))
    assert m.valuation.valuation_model == "ROE_PB"
    assert m.roe <= 0
    tangible_bvps = (1000.0 - 400.0) / 100.0
    assert m.valuation.fair_value_share == pytest.approx(0.1 * tangible_bvps)


def test_roe_pb_main_branch_is_noop_regardless_of_goodwill():
    # roe > 0 branch: bvps * (roe/Ke) - equity cancels out algebraically
    # (bvps=equity/shares, roe=NI/equity), so goodwill must NOT move the
    # fair value here, only the displayed BVPS/roe would differ if raw
    # figures were swapped for tangible ones (they aren't, by design).
    baseline = compute_bank_metrics(make_bank_data(cash_dividends_paid=None, dividend_yield=0.0))
    with_goodwill = compute_bank_metrics(make_bank_data(
        cash_dividends_paid=None, dividend_yield=0.0,
        goodwill=(400.0, 400.0, 400.0, 400.0),
    ))
    assert with_goodwill.valuation.valuation_model == "ROE_PB"
    assert with_goodwill.valuation.fair_value_share == pytest.approx(baseline.valuation.fair_value_share)
    # Displayed BVPS stays raw (unadjusted) in the main branch either way.
    assert with_goodwill.bvps == pytest.approx(baseline.bvps)


def test_ddm_selected_via_dividend_yield_even_with_zero_cash_div_paid():
    m = compute_bank_metrics(make_bank_data(cash_dividends_paid=(0.0, 0.0, 0.0, 0.0), dividend_yield=0.015))
    assert m.valuation.valuation_model == "DDM"


def test_ddm_cagr_div_clamped_to_8_pct_ceiling():
    # DPS quadruples over 3 years -> raw CAGR ~59%, clamped to 8%.
    m = compute_bank_metrics(make_bank_data(cash_dividends_paid=(-12.5, -25.0, -37.5, -50.0)))
    assert m.valuation.valuation_model == "DDM"
    assert m.cagr_div == pytest.approx(0.08)


def test_ddm_defaults_cagr_div_to_3_pct_when_dps_zero_at_start():
    # No dividend paid in the first year -> DPS window starts at 0, which
    # fails the "both ends positive" check -> default 3% (spec Section 5.2).
    m = compute_bank_metrics(make_bank_data(cash_dividends_paid=(0.0, -20.0, -30.0, -50.0)))
    assert m.valuation.valuation_model == "DDM"
    assert m.cagr_div == pytest.approx(0.03)


def test_required_return_overrides_capm_cost_of_equity_for_banks():
    m_default = compute_bank_metrics(make_bank_data())
    assert m_default.valuation.required_return_used is False
    assert m_default.valuation.cost_of_equity == pytest.approx(0.09)  # beta=1.0: 4% + 1.0*5%

    m_override = compute_bank_metrics(make_bank_data(), required_return=0.12)
    assert m_override.valuation.required_return_used is True
    assert m_override.valuation.cost_of_equity == pytest.approx(0.12)


# ── Section 4.2: Minor sins ──────────────────────────────────────────────

def test_nii_declining_fires():
    # commissions_income raised to offset the NII drop so net_op_income
    # (NII + commissions) stays flat and negative_jaws doesn't co-fire -
    # isolates nii_declining alone.
    m = compute_bank_metrics(make_bank_data(
        net_interest_income=(350.0, 350.0, 350.0, 330.0),
        commissions_income=(80.0, 80.0, 80.0, 100.0),
    ))
    assert sin_ids(m.scoring.minor_sins) == {"nii_declining"}
    assert m.scoring.minor_score == pytest.approx(1.0)
    assert "КУПИТЬ" in m.scoring.verdict


def test_provision_spike_above_15_pct_fires():
    m = compute_bank_metrics(make_bank_data(
        credit_loss_provision=(30.0, 30.0, 30.0, 40.0),  # +33% YoY
    ))
    assert sin_ids(m.scoring.minor_sins) == {"provision_spike"}
    assert m.scoring.minor_score == pytest.approx(1.0)


def test_provision_growth_at_or_below_15_pct_does_not_fire():
    m = compute_bank_metrics(make_bank_data(
        credit_loss_provision=(30.0, 30.0, 30.0, 34.5),  # exactly +15%
    ))
    assert "provision_spike" not in sin_ids(m.scoring.minor_sins)


def test_dilution_fires_above_1_5_pct_growth():
    m = compute_bank_metrics(make_bank_data(diluted_shares=(100.0, 100.0, 100.0, 102.0)))
    assert sin_ids(m.scoring.minor_sins) == {"dilution"}
    assert m.scoring.minor_score == pytest.approx(1.0)


def test_buyback_bonus_floors_score_at_zero():
    m = compute_bank_metrics(make_bank_data(diluted_shares=(100.0, 100.0, 100.0, 98.0)))
    assert sin_ids(m.scoring.minor_sins) == {"buyback_bonus"}
    assert m.scoring.minor_score == 0.0


def test_ltd_above_100_pct_fires():
    m = compute_bank_metrics(make_bank_data(net_loans=(2000.0, 2000.0, 2000.0, 2600.0)))
    assert m.ltd_ratio == pytest.approx(2600.0 / 2500.0)
    assert sin_ids(m.scoring.minor_sins) == {"ltd_imbalance"}
    assert m.scoring.minor_score == pytest.approx(0.5)


def test_ltd_below_60_pct_fires():
    m = compute_bank_metrics(make_bank_data(
        net_loans=(2000.0, 2000.0, 2000.0, 1000.0),
        total_deposits=(2500.0, 2500.0, 2500.0, 2500.0),
    ))
    assert m.ltd_ratio == pytest.approx(0.4)
    assert sin_ids(m.scoring.minor_sins) == {"ltd_imbalance"}


def test_ltd_within_60_100_pct_range_fires_no_sin():
    m = compute_bank_metrics(make_bank_data(net_loans=(2000.0, 2000.0, 2000.0, 2000.0)))
    assert m.ltd_ratio == pytest.approx(0.8)
    assert m.scoring.sins == []


def test_dead_cash_fires_on_cash_spike_plus_loan_shrinkage():
    m = compute_bank_metrics(make_bank_data(
        cash_and_equiv=(300.0, 300.0, 300.0, 400.0),  # +33%
        net_loans=(2000.0, 2000.0, 2000.0, 1900.0),   # shrinking
    ))
    assert sin_ids(m.scoring.minor_sins) == {"dead_cash"}
    assert m.scoring.minor_score == pytest.approx(0.5)


def test_negative_jaws_fires_when_opex_outgrows_net_op_income():
    m = compute_bank_metrics(make_bank_data(
        non_interest_expense=(200.0, 200.0, 200.0, 240.0),  # +20%
        # NII stays 350, commissions stays 80 -> net_op_income flat (0% growth)
    ))
    assert sin_ids(m.scoring.minor_sins) == {"negative_jaws"}
    assert m.scoring.minor_score == pytest.approx(0.5)


def test_commissions_declining_fires():
    # net_interest_income raised to offset the commissions drop so
    # net_op_income stays flat and negative_jaws doesn't co-fire.
    m = compute_bank_metrics(make_bank_data(
        net_interest_income=(350.0, 350.0, 350.0, 360.0),
        commissions_income=(80.0, 80.0, 80.0, 70.0),
    ))
    assert sin_ids(m.scoring.minor_sins) == {"commissions_declining"}
    assert m.scoring.minor_score == pytest.approx(0.3)


def test_net_income_declining_fires():
    m = compute_bank_metrics(make_bank_data(net_income=(150.0, 150.0, 150.0, 140.0)))
    assert sin_ids(m.scoring.minor_sins) == {"net_income_declining"}
    assert m.scoring.minor_score == pytest.approx(0.3)


# ── Section 4.3: Verdict scale boundaries ────────────────────────────────

def test_minor_score_exactly_1_0_is_buy_boundary_inclusive():
    # provision_spike alone (1.0) - unrelated to the NII/commissions/opex
    # JAWS formula, so it isolates cleanly.
    m = compute_bank_metrics(make_bank_data(credit_loss_provision=(30.0, 30.0, 30.0, 40.0)))
    assert sin_ids(m.scoring.minor_sins) == {"provision_spike"}
    assert m.scoring.minor_score == pytest.approx(1.0)
    assert "КУПИТЬ" in m.scoring.verdict


def test_minor_score_2_6_is_skip():
    m = compute_bank_metrics(make_bank_data(
        net_interest_income=(350.0, 350.0, 350.0, 330.0),      # nii_declining: +1.0
        credit_loss_provision=(30.0, 30.0, 30.0, 40.0),        # provision_spike: +1.0
        commissions_income=(80.0, 80.0, 80.0, 70.0),           # commissions_declining: +0.3
        # non_interest_expense shrinks faster than net_op_income
        # (NII+commissions: 430 -> 400, -6.98%) so negative_jaws does NOT
        # co-fire (opex growth -15% is not > -6.98%).
        non_interest_expense=(200.0, 200.0, 200.0, 170.0),
        net_income=(150.0, 150.0, 150.0, 140.0),               # net_income_declining: +0.3
    ))
    assert m.scoring.critical_sins == []
    assert sin_ids(m.scoring.minor_sins) == {
        "nii_declining", "provision_spike", "commissions_declining", "net_income_declining",
    }
    assert m.scoring.minor_score == pytest.approx(2.6)
    assert "ПРОПУСТИТЬ" in m.scoring.verdict


def test_max_minor_score_matches_weight_table():
    # 1.0x3 (nii/provision/dilution) + 0.5x3 (ltd/dead_cash/jaws) + 0.3x2 (commissions/net_income) = 5.1
    assert BANK_MAX_MINOR_SCORE == pytest.approx(5.1)
