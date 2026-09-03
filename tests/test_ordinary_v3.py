"""Ordinary v3 engine tests (spec Section 2/4,
docs/spec/step4-ordinary-v3-implementation-spec.md).

Same style as tests/test_verdict_scoring.py: synthetic financials/balance/
cashflow DataFrames built directly, compute_metrics() called on them - no
network access. A separate file (rather than extending
test_verdict_scoring.py, which the spec's Section 4.1 literally names) so
that file - and the 21 Ordinary v2 tests it holds - never needs to change,
same reasoning as tests/test_bank_analyzer.py and tests/test_reit_analyzer.py
in Steps 2-3.

Uses 4 years (not test_verdict_scoring.py's 2) since the buyback-distortion
bypass explicitly checks "all available years, up to 4".
"""

import pandas as pd
import pytest

from financial_analyzer import compute_metrics

YEARS = ["2022", "2023", "2024", "2025"]


def _df(rows):
    return pd.DataFrame(rows, index=YEARS).T


def make_data(
    revenue=(1000.0, 1000.0, 1000.0, 1000.0),
    operating_income=(200.0, 200.0, 200.0, 200.0),
    net_income=(150.0, 150.0, 150.0, 150.0),
    normalized_income=None,
    eps=(2.0, 2.0, 2.0, 2.0),
    interest_expense=None,
    curr_assets=(500.0, 500.0, 500.0, 500.0),
    curr_liab=(200.0, 200.0, 200.0, 200.0),
    total_assets=(2000.0, 2000.0, 2000.0, 2000.0),
    total_liab=(800.0, 800.0, 800.0, 800.0),
    goodwill=(0.0, 0.0, 0.0, 0.0),
    equity=(1200.0, 1200.0, 1200.0, 1200.0),
    long_term_debt=(100.0, 100.0, 100.0, 100.0),
    lease_liabilities=None,
    cash=(300.0, 300.0, 300.0, 300.0),
    fcf=(180.0, 180.0, 180.0, 180.0),
    diluted_shares=(105.0, 104.0, 102.0, 100.0),
    current_debt=None,
    cash_dividends_paid=None,
    dividend_yield=0.0,
    dividend_rate=0.0,
    industry="",
    sector="",
):
    """Flat, healthy 4-year baseline with a steadily shrinking share count
    (buyback in progress) by default - zero sins otherwise, DCF valuation,
    no dividends. Pass any row as a 4-tuple to override just that row.
    """
    fin_rows = {
        "Total Revenue": list(revenue),
        "Operating Income": list(operating_income),
        "Net Income": list(net_income),
        "Diluted EPS": list(eps),
        "Diluted Average Shares": list(diluted_shares),
    }
    if interest_expense is not None:
        fin_rows["Interest Expense"] = list(interest_expense)
    if normalized_income is not None:
        fin_rows["Normalized Income"] = list(normalized_income)
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
    if lease_liabilities is not None:
        bal_rows["Long Term Capital Lease Obligation"] = list(lease_liabilities)
    if current_debt is not None:
        bal_rows["Current Debt"] = list(current_debt)
    cf_rows = {"Free Cash Flow": list(fcf)}
    if cash_dividends_paid is not None:
        cf_rows["Cash Dividends Paid"] = list(cash_dividends_paid)
    return {
        "financials": _df(fin_rows),
        "balance": _df(bal_rows),
        "cashflow": _df(cf_rows),
        "price": 50.0,
        "shares": 100.0,
        "beta": 1.0,
        "info": {
            "dividendYield": dividend_yield, "dividendRate": dividend_rate,
            "industry": industry, "sector": sector,
        },
    }


def sin_ids(sins):
    return {s.id for s in sins}


# ── Section 2.1: Equity <= 0 smart bypass ────────────────────────────────

def test_equity_negative_bypassed_when_all_three_conditions_met():
    m = compute_metrics(make_data(
        equity=(-50.0, -60.0, -70.0, -80.0),  # negative all 4 years
        operating_income=(200.0, 200.0, 200.0, 200.0),  # positive all 4
        fcf=(180.0, 180.0, 180.0, 180.0),  # positive all 4
        diluted_shares=(110.0, 108.0, 104.0, 100.0),  # steadily shrinking
    ))
    assert "equity_negative" not in sin_ids(m.scoring.critical_sins)
    assert sin_ids(m.scoring.minor_sins) & {"technical_negative_equity"} == {"technical_negative_equity"}
    tne = next(s for s in m.scoring.minor_sins if s.id == "technical_negative_equity")
    assert tne.weight == pytest.approx(1.0)
    assert "ПРОПУСТИТЬ" not in m.scoring.verdict or m.scoring.minor_score > 2.5  # verdict driven by score, not auto-SKIP


def test_equity_negative_stays_critical_when_operating_income_negative_one_year():
    m = compute_metrics(make_data(
        equity=(-50.0, -60.0, -70.0, -80.0),
        operating_income=(200.0, -10.0, 200.0, 200.0),  # one bad year
        fcf=(180.0, 180.0, 180.0, 180.0),
        diluted_shares=(110.0, 108.0, 104.0, 100.0),
    ))
    assert sin_ids(m.scoring.critical_sins) == {"equity_negative"}
    assert "technical_negative_equity" not in sin_ids(m.scoring.minor_sins)
    assert "ПРОПУСТИТЬ" in m.scoring.verdict


def test_equity_negative_stays_critical_when_fcf_negative_one_year():
    m = compute_metrics(make_data(
        equity=(-50.0, -60.0, -70.0, -80.0),
        operating_income=(200.0, 200.0, 200.0, 200.0),
        fcf=(180.0, -10.0, 180.0, 180.0),  # one bad year
        diluted_shares=(110.0, 108.0, 104.0, 100.0),
    ))
    assert sin_ids(m.scoring.critical_sins) == {"equity_negative"}
    assert "technical_negative_equity" not in sin_ids(m.scoring.minor_sins)


def test_equity_negative_stays_critical_when_shares_not_declining():
    m = compute_metrics(make_data(
        equity=(-50.0, -60.0, -70.0, -80.0),
        operating_income=(200.0, 200.0, 200.0, 200.0),
        fcf=(180.0, 180.0, 180.0, 180.0),
        diluted_shares=(100.0, 100.0, 100.0, 100.0),  # flat, no buyback proof
    ))
    assert sin_ids(m.scoring.critical_sins) == {"equity_negative"}
    assert "technical_negative_equity" not in sin_ids(m.scoring.minor_sins)


# ── Section 2.2.1: lt_insolvency smart bypass ────────────────────────────

def test_lt_insolvency_bypassed_when_all_three_conditions_met():
    # long-term assets (Total Assets - Current Assets - Goodwill) = 1500,
    # long-term liab (Total Liab - Current Liab) = 600 by default - flip it
    # so long-term liab exceeds long-term assets (goodwill-adjusted).
    m = compute_metrics(make_data(
        total_assets=(1000.0, 1000.0, 1000.0, 1000.0),  # LT assets = 500
        total_liab=(900.0, 900.0, 900.0, 900.0),        # LT liab = 700 > 500
        operating_income=(200.0, 200.0, 200.0, 200.0),
        fcf=(180.0, 180.0, 180.0, 180.0),
        diluted_shares=(110.0, 108.0, 104.0, 100.0),
    ))
    assert "lt_insolvency" not in sin_ids(m.scoring.critical_sins)
    assert "technical_lt_insolvency" in sin_ids(m.scoring.minor_sins)
    tli = next(s for s in m.scoring.minor_sins if s.id == "technical_lt_insolvency")
    assert tli.weight == pytest.approx(1.0)


def test_lt_insolvency_stays_critical_without_buyback_proof():
    m = compute_metrics(make_data(
        total_assets=(1000.0, 1000.0, 1000.0, 1000.0),
        total_liab=(900.0, 900.0, 900.0, 900.0),
        diluted_shares=(100.0, 100.0, 100.0, 100.0),  # flat, no buyback proof
    ))
    assert sin_ids(m.scoring.critical_sins) == {"lt_insolvency"}
    assert "technical_lt_insolvency" not in sin_ids(m.scoring.minor_sins)


# ── Section 2.2 Scenario 2: Current Ratio bypass via ICR proxy ───────────

def test_cr_bypass_scenario2_fires_with_safe_leverage_and_strong_icr():
    # CR = 270/300 = 0.9 < 1.0; current_debt omitted (Scenario 1 unusable).
    # Net Debt = 100 (LT debt) - 300 (cash) = -200... need a POSITIVE net
    # debt to exercise Scenario 2, so raise debt above cash.
    m = compute_metrics(make_data(
        curr_assets=(400.0, 400.0, 400.0, 270.0), curr_liab=(300.0, 300.0, 300.0, 300.0),
        long_term_debt=(600.0, 600.0, 600.0, 600.0), cash=(100.0, 100.0, 100.0, 100.0),
        # Net Debt = 600-100 = 500; Operating Income = 200 -> ND/OpInc = 2.5 (< 4.0)
        interest_expense=(30.0, 30.0, 30.0, 30.0),  # ICR = 200/30 = 6.67 (> 4.0)
    ))
    assert m.current_ratio == pytest.approx(0.9)
    assert m.scoring.critical_sins == []
    assert "cr_below_1_bypassed" in sin_ids(m.scoring.minor_sins)


def test_cr_bypass_scenario2_does_not_fire_above_leverage_cutoff():
    m = compute_metrics(make_data(
        curr_assets=(400.0, 400.0, 400.0, 270.0), curr_liab=(300.0, 300.0, 300.0, 300.0),
        long_term_debt=(1200.0, 1200.0, 1200.0, 1200.0), cash=(100.0, 100.0, 100.0, 100.0),
        # Net Debt = 1100; ND/OpInc = 1100/200 = 5.5 (> 4.0) -> fails
        interest_expense=(30.0, 30.0, 30.0, 30.0),
    ))
    assert sin_ids(m.scoring.critical_sins) == {"cr_below_1"}


def test_cr_bypass_scenario2_does_not_fire_below_icr_cutoff():
    m = compute_metrics(make_data(
        curr_assets=(400.0, 400.0, 400.0, 270.0), curr_liab=(300.0, 300.0, 300.0, 300.0),
        long_term_debt=(600.0, 600.0, 600.0, 600.0), cash=(100.0, 100.0, 100.0, 100.0),
        interest_expense=(80.0, 80.0, 80.0, 80.0),  # ICR = 200/80 = 2.5 (< 4.0) -> fails
    ))
    assert sin_ids(m.scoring.critical_sins) == {"cr_below_1"}


def test_cr_bypass_scenario2_auto_passes_icr_when_interest_expense_missing():
    m = compute_metrics(make_data(
        curr_assets=(400.0, 400.0, 400.0, 270.0), curr_liab=(300.0, 300.0, 300.0, 300.0),
        long_term_debt=(600.0, 600.0, 600.0, 600.0), cash=(100.0, 100.0, 100.0, 100.0),
        # No Interest Expense row at all -> ICR auto-passes; ND/OpInc = 2.5 still < 4.0
    ))
    assert m.scoring.critical_sins == []
    assert "cr_below_1_bypassed" in sin_ids(m.scoring.minor_sins)


def test_cr_bypass_scenario2_does_not_fire_for_net_cash_company():
    # Regression guard (see tests/test_verdict_scoring.py::
    # test_cr_below_1_stays_critical_when_current_debt_row_is_missing):
    # net debt <= 0 (more cash than debt) must not trivially satisfy the
    # leverage scenario - that's Scenario 1's territory, not Scenario 2's.
    m = compute_metrics(make_data(
        curr_assets=(400.0, 400.0, 400.0, 270.0), curr_liab=(300.0, 300.0, 300.0, 300.0),
        long_term_debt=(100.0, 100.0, 100.0, 100.0), cash=(300.0, 300.0, 300.0, 300.0),
        # Net Debt = 100-300 = -200 (net cash)
    ))
    assert sin_ids(m.scoring.critical_sins) == {"cr_below_1"}


# ── Section 2.3: DCF -> DDM auto-switch ──────────────────────────────────

def test_ddm_triggers_on_negative_equity_plus_dividends():
    m = compute_metrics(make_data(
        equity=(-50.0, -60.0, -70.0, -80.0),
        cash_dividends_paid=(-200.0, -210.0, -220.0, -230.0),
        diluted_shares=(110.0, 108.0, 104.0, 100.0),
        dividend_yield=0.03,
    ))
    assert m.valuation.valuation_model == "DDM"
    assert m.cagr_div is not None
    assert 0.02 <= m.cagr_div <= 0.10
    assert m.dps_last == pytest.approx(230.0 / 100.0)


def test_ddm_triggers_on_high_debt_to_equity_plus_dividends():
    m = compute_metrics(make_data(
        equity=(1200.0, 1200.0, 1200.0, 1000.0),
        long_term_debt=(2500.0, 2500.0, 2500.0, 2500.0),  # D/E = 2.5 > 2.0
        cash_dividends_paid=(-200.0, -210.0, -220.0, -230.0),
        dividend_rate=1.5,
    ))
    assert m.debt_to_equity_ratio == pytest.approx(2.5)
    assert m.valuation.valuation_model == "DDM"


def test_ddm_not_triggered_without_dividends_even_if_capital_distorted():
    m = compute_metrics(make_data(equity=(-50.0, -60.0, -70.0, -80.0)))
    assert m.valuation.valuation_model == "DCF"
    assert m.cagr_div is None


def test_ddm_not_triggered_when_capital_is_healthy():
    m = compute_metrics(make_data(
        cash_dividends_paid=(-200.0, -210.0, -220.0, -230.0), dividend_yield=0.03,
    ))
    # equity positive (1200), D/E = 100/1200 = 0.08 (< 2.0) -> stays DCF
    assert m.valuation.valuation_model == "DCF"


# ── V01: tangible equity (goodwill-adjusted) drives the D/E trigger ─────

def test_ddm_triggers_on_high_tangible_debt_to_equity_masked_by_goodwill():
    # Raw D/E = 2500/2000 = 1.25 (< 2.0, would NOT trigger pre-V01).
    # Tangible D/E = 2500/(2000-1200) = 2500/800 = 3.125 (> 2.0, DOES trigger).
    m = compute_metrics(make_data(
        equity=(2000.0, 2000.0, 2000.0, 2000.0),
        goodwill=(1200.0, 1200.0, 1200.0, 1200.0),
        long_term_debt=(2500.0, 2500.0, 2500.0, 2500.0),
        cash_dividends_paid=(-200.0, -210.0, -220.0, -230.0),
        dividend_rate=1.5,
    ))
    assert m.debt_to_equity_ratio == pytest.approx(2500.0 / 800.0)
    assert m.valuation.valuation_model == "DDM"


def test_ddm_not_triggered_when_goodwill_is_zero_no_op():
    # Same shape as test_ddm_not_triggered_when_capital_is_healthy but
    # explicit goodwill=0 - confirms tangible_equity == raw equity is a
    # true no-op, not just an accident of the default fixture.
    m = compute_metrics(make_data(
        equity=(1200.0, 1200.0, 1200.0, 1200.0),
        goodwill=(0.0, 0.0, 0.0, 0.0),
        cash_dividends_paid=(-200.0, -210.0, -220.0, -230.0), dividend_yield=0.03,
    ))
    assert m.valuation.valuation_model == "DCF"


def test_ddm_cagr_div_clamped_to_10_pct_ceiling():
    m = compute_metrics(make_data(
        equity=(-50.0, -60.0, -70.0, -80.0),
        cash_dividends_paid=(-50.0, -100.0, -150.0, -230.0),  # steep raw growth
        diluted_shares=(110.0, 108.0, 104.0, 100.0),
        dividend_yield=0.03,
    ))
    assert m.valuation.valuation_model == "DDM"
    assert m.cagr_div == pytest.approx(0.10)


def test_ddm_defaults_cagr_div_to_5_pct_when_dps_unavailable_at_start():
    m = compute_metrics(make_data(
        equity=(-50.0, -60.0, -70.0, -80.0),
        cash_dividends_paid=(0.0, -100.0, -150.0, -230.0),  # zero at the start
        diluted_shares=(110.0, 108.0, 104.0, 100.0),
        dividend_yield=0.03,
    ))
    assert m.valuation.valuation_model == "DDM"
    assert m.cagr_div == pytest.approx(0.05)


def test_ddm_required_return_overrides_capm_cost_of_equity():
    m = compute_metrics(make_data(
        equity=(-50.0, -60.0, -70.0, -80.0),
        cash_dividends_paid=(-200.0, -210.0, -220.0, -230.0),
        diluted_shares=(110.0, 108.0, 104.0, 100.0),
        dividend_yield=0.03,
    ), required_return=0.12)
    assert m.valuation.valuation_model == "DDM"
    assert m.valuation.cost_of_equity == pytest.approx(0.12)
