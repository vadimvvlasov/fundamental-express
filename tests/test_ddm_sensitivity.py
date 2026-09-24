"""DDM sensitivity matrix tests.

Covers the DDM-branch gap: the DCF path always had a sensitivity matrix,
the DDM auto-switch path (negative book equity + dividends) had none.
Builds synthetic DataFrames directly (same pattern as
tests/test_verdict_scoring.py:make_data) and calls compute_metrics() -
no network access, no yfinance involved.
"""

import pandas as pd
import pytest

from financial_analyzer import compute_metrics
from fundamental_express.domain.valuation import ddm_fair_value, ddm_sensitivity

YEARS = ["2023", "2024"]


def _df(rows):
    return pd.DataFrame(rows, index=YEARS).T


def make_ddm_data():
    """Buyback-distorted balance sheet (negative equity from repurchases,
    like MCD) with a dividend history - triggers the Ordinary v3 DDM
    auto-switch instead of the classic FCF-DCF."""
    financials = _df({
        "Total Revenue": [25000.0, 26000.0],
        "Operating Income": [11000.0, 11500.0],
        "Net Income": [8000.0, 8200.0],
        "Diluted EPS": [11.0, 11.5],
        "Cost Of Revenue": [15000.0, 15500.0],
        "Diluted Average Shares": [720.0, 710.0],
    })
    balance = _df({
        "Total Current Assets": [4500.0, 4200.0],
        "Total Current Liabilities": [3800.0, 4300.0],
        "Total Assets": [35000.0, 36000.0],
        "Total Liabilities Net Minority Interest": [39000.0, 38000.0],
        "Goodwill": [2500.0, 2500.0],
        "Stockholders Equity": [-4000.0, -2000.0],
        "Long Term Debt": [35000.0, 34000.0],
        "Cash And Cash Equivalents": [4000.0, 4500.0],
    })
    cashflow = _df({
        "Free Cash Flow": [6500.0, 7000.0],
        "Cash Dividends Paid": [-4800.0, -5100.0],
    })
    return {
        "financials": financials,
        "balance": balance,
        "cashflow": cashflow,
        "price": 238.0,
        "shares": 700.0,
        "beta": 0.41,
        "info": {"dividendYield": 0.03, "dividendRate": 6.0},
    }


def test_ddm_path_carries_sensitivity_matrix():
    m = compute_metrics(make_ddm_data())
    assert m.valuation.valuation_model == "DDM"
    assert m.ddm_sensitivity_headers is not None
    assert m.ddm_sensitivity_rows is not None
    assert len(m.ddm_sensitivity_headers) == 6  # label + 5 Ke columns
    assert len(m.ddm_sensitivity_rows) == 5  # 5 CAGR_div rows
    assert all(len(r) == 6 for r in m.ddm_sensitivity_rows)


def test_ddm_matrix_center_cell_matches_fair_value():
    m = compute_metrics(make_ddm_data())
    # Row 2 = base CAGR_div, column 3 = base Ke (offsets are symmetric).
    assert m.ddm_sensitivity_rows[2][3] == f"{m.valuation.fair_value_share:.2f} USD"


def test_ddm_fair_value_helper_reproduces_valuation():
    m = compute_metrics(make_ddm_data())
    assert ddm_fair_value(
        m.dps_last, m.cagr_div, m.valuation.cost_of_equity, m.terminal_g
    ) == pytest.approx(m.valuation.fair_value_share)


def test_ddm_matrix_marks_undefined_gordon_cells_na():
    # Ke=3% with g=2.5%: the two leftmost Ke columns (1.50%, 2.25%) sit at
    # or below terminal growth - Gordon is undefined there.
    headers, rows = ddm_sensitivity(7.0, 0.08, 0.03, 0.025)
    assert headers[1] == "1.50%"
    assert headers[2] == "2.25%"
    assert rows[2][1] == "N/A"
    assert rows[2][2] == "N/A"
    assert rows[2][3].endswith("USD")


def test_dcf_path_has_no_ddm_matrix():
    from test_verdict_scoring import make_data
    m = compute_metrics(make_data())
    assert m.valuation.valuation_model == "DCF"
    assert m.ddm_sensitivity_headers is None
    assert m.ddm_sensitivity_rows is None
