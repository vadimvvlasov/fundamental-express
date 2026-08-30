"""Golden fixture: one healthy, network-free REIT data dict, shaped exactly
like financial_analyzer.get_company_data()'s return value.

Zero sins, comfortable AFFO payout by construction - mirrors the flat,
healthy baseline in tests/test_reit_analyzer.py's make_reit_data() (FFO =
150+50-0 = 200, AFFO = 200-20 = 180, NOI = 300-100-0 = 200 both years).
"""

import pandas as pd

YEARS = ["2024", "2025"]


def _df(rows):
    return pd.DataFrame(rows, index=YEARS).T


M = 1_000_000  # fixture dollar figures are stated in whole USD, at "millions" scale


def build_reit_data():
    fin_rows = {
        "Net Income": [150.0 * M, 150.0 * M],
        "Total Revenue": [300.0 * M, 300.0 * M],
        "Operating Expense": [100.0 * M, 100.0 * M],
        "Diluted Average Shares": [100.0 * M, 100.0 * M],
    }
    bal_rows = {
        "Construction In Progress": [0.0, 0.0],
        "Receivables": [10.0 * M, 10.0 * M],
        "Cash and Cash Equivalents": [20.0 * M, 20.0 * M],
        "Total Liabilities Net Minority Interest": [800.0 * M, 800.0 * M],
        "Total Debt": [400.0 * M, 400.0 * M],
        "Stockholders Equity": [1000.0 * M, 1000.0 * M],
    }
    cf_rows = {
        "Depreciation And Amortization": [50.0 * M, 50.0 * M],
        "Capital Expenditure": [-20.0 * M, -20.0 * M],
        "Cash Dividends Paid": [-150.0 * M, -150.0 * M],
    }
    return {
        "ticker": "PROPCO",
        "name": "Propco Realty Trust (Fixture)",
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
        "info": {},
    }
