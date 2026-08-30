"""Golden fixture: one healthy, network-free bank data dict, shaped exactly
like financial_analyzer.get_company_data()'s return value.

Zero sins, DDM valuation path (cash_dividends_paid > 0) by construction -
mirrors the flat, healthy baseline in tests/test_bank_analyzer.py's
make_bank_data().
"""

import pandas as pd

YEARS = ["2022", "2023", "2024", "2025"]


def _df(rows):
    return pd.DataFrame(rows, index=YEARS).T


M = 1_000_000  # fixture dollar figures are stated in whole USD, at "millions" scale


def build_bank_data():
    fin_rows = {
        "Interest Income": [500.0 * M, 500.0 * M, 500.0 * M, 500.0 * M],
        "Interest Expense": [150.0 * M, 150.0 * M, 150.0 * M, 150.0 * M],
        "Fees and Commissions": [80.0 * M, 80.0 * M, 80.0 * M, 80.0 * M],
        "Trading Revenue": [20.0 * M, 20.0 * M, 20.0 * M, 20.0 * M],
        "Provision for Credit Losses": [30.0 * M, 30.0 * M, 30.0 * M, 30.0 * M],
        "Non Interest Expense": [200.0 * M, 200.0 * M, 200.0 * M, 200.0 * M],
        "Net Income": [150.0 * M, 150.0 * M, 150.0 * M, 150.0 * M],
        "Preferred Stock Dividends": [0.0, 0.0, 0.0, 0.0],
        "Diluted Average Shares": [100.0 * M, 100.0 * M, 100.0 * M, 100.0 * M],
    }
    bal_rows = {
        "Cash and Cash Equivalents": [300.0 * M, 300.0 * M, 300.0 * M, 300.0 * M],
        "Net Loans": [2000.0 * M, 2000.0 * M, 2000.0 * M, 2000.0 * M],
        "Total Deposits": [2500.0 * M, 2500.0 * M, 2500.0 * M, 2500.0 * M],
        "Long Term Debt": [400.0 * M, 400.0 * M, 400.0 * M, 400.0 * M],
        "Stockholders Equity": [1000.0 * M, 1000.0 * M, 1000.0 * M, 1000.0 * M],
    }
    cf_rows = {
        "Cash Dividends Paid": [-50.0 * M, -50.0 * M, -50.0 * M, -50.0 * M],
    }
    return {
        "ticker": "GOLDBANK",
        "name": "Goldbank Financial Group (Fixture)",
        "price": 50.0,
        "shares": 100.0 * M,
        "beta": 1.0,
        "financials": _df(fin_rows),
        "balance": _df(bal_rows),
        "cashflow": _df(cf_rows),
        "is_sample": False,
        "price_kind": "последняя сделка (regularMarketPrice)",
        "quote_time_label": "2026-01-15 16:00 EST",
        "fx_rate": 1.0,
        "financial_currency": "USD",
        "trading_currency": "USD",
        "info": {"dividendYield": 0.02},
    }
