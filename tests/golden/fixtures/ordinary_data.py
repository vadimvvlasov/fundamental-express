"""Golden fixture: one healthy, network-free ordinary-company data dict,
shaped exactly like financial_analyzer.get_company_data()'s return value.

Zero sins by construction (revenue/operating income/net income/equity/FCF
all rising, current ratio and margins flat, share count flat) so the
resulting report is a stable BUY snapshot with no smart-bypass or DDM
branch involved - see tests/test_verdict_scoring.py's make_data() for the
same baseline pattern this mirrors.
"""

import pandas as pd

YEARS = ["2021", "2022", "2023", "2024"]


def _df(rows):
    return pd.DataFrame(rows, index=YEARS).T


M = 1_000_000  # fixture dollar figures are stated in whole USD, at "millions" scale


def build_ordinary_data():
    fin_rows = {
        "Total Revenue": [1000.0 * M, 1050.0 * M, 1100.0 * M, 1150.0 * M],
        "Operating Income": [200.0 * M, 210.0 * M, 220.0 * M, 230.0 * M],
        "Net Income": [150.0 * M, 157.5 * M, 165.0 * M, 172.5 * M],
        "Diluted EPS": [1.50, 1.58, 1.65, 1.73],
        "Cost Of Revenue": [600.0 * M, 630.0 * M, 660.0 * M, 690.0 * M],
        "Diluted Average Shares": [100.0 * M, 100.0 * M, 100.0 * M, 100.0 * M],
    }
    bal_rows = {
        "Total Current Assets": [500.0 * M, 520.0 * M, 540.0 * M, 560.0 * M],
        "Total Current Liabilities": [200.0 * M, 205.0 * M, 210.0 * M, 215.0 * M],
        "Total Assets": [2000.0 * M, 2050.0 * M, 2100.0 * M, 2150.0 * M],
        "Total Liabilities Net Minority Interest": [800.0 * M, 810.0 * M, 820.0 * M, 830.0 * M],
        "Goodwill": [0.0, 0.0, 0.0, 0.0],
        "Stockholders Equity": [1200.0 * M, 1240.0 * M, 1280.0 * M, 1320.0 * M],
        "Long Term Debt": [100.0 * M, 100.0 * M, 100.0 * M, 100.0 * M],
        "Cash And Cash Equivalents": [300.0 * M, 310.0 * M, 320.0 * M, 330.0 * M],
    }
    cf_rows = {
        "Free Cash Flow": [180.0 * M, 188.0 * M, 196.0 * M, 204.0 * M],
    }
    return {
        "ticker": "ACME",
        "name": "Acme Ordinary Co. (Fixture)",
        "price": 45.0,
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
