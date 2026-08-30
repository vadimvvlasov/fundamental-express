"""Labeled SAMPLE fallback data (--allow-sample), used only when a real
Yahoo Finance fetch fails after every retry. Moved verbatim out of
financial_analyzer.py (docs/spec/refactor-tasks.md T09).
"""

from datetime import datetime

import pandas as pd


def _sample_data(ticker):
    years = ["2021", "2022", "2023", "2024"]

    fin_data = {
        "Total Revenue": [365817000000, 394328000000, 383285000000, 391035000000],
        "Operating Income": [108949000000, 119437000000, 114301000000, 117823000000],
        "Net Income": [94680000000, 99803000000, 96995000000, 100913000000],
        "Diluted EPS": [5.61, 6.11, 6.13, 6.43],
    }
    financials_df = pd.DataFrame(fin_data, index=years).T

    bal_data = {
        "Total Current Assets": [134836000000, 135405000000, 143566000000, 149200000000],
        "Total Current Liabilities": [125481000000, 153982000000, 145308000000, 140000000000],
        "Total Assets": [351002000000, 352755000000, 352581000000, 365000000000],
        "Total Liabilities Net Minority Interest": [287912000000, 302083000000, 290437000000, 295000000000],
        "Goodwill": [0, 0, 0, 0],
        "Stockholders Equity": [63090000000, 50672000000, 62144000000, 70000000000],
        "Total Debt": [124719000000, 120069000000, 111088000000, 105000000000],
        "Cash And Cash Equivalents": [34940000000, 23646000000, 29965000000, 31000000000],
    }
    balance_df = pd.DataFrame(bal_data, index=years).T

    cf_data = {
        "Free Cash Flow": [92953000000, 111443000000, 99584000000, 104000000000],
        "Operating Cash Flow": [104038000000, 122151000000, 110574000000, 115000000000],
    }
    cashflow_df = pd.DataFrame(cf_data, index=years).T

    return {
        "ticker": ticker.upper(),
        "name": "Apple Inc. (Sample)" if ticker.upper() == "AAPL" else f"{ticker.upper()} (SAMPLE - NOT REAL DATA)",
        "price": 180.0,
        "shares": 15000000000,
        "beta": 1.1,
        "financials": financials_df,
        "balance": balance_df,
        "cashflow": cashflow_df,
        "is_sample": True,
        "price_kind": "SAMPLE - НЕ РЕАЛЬНАЯ ЦЕНА",
        "quote_time_label": f"{datetime.now().strftime('%Y-%m-%d %H:%M')} (время запуска скрипта на SAMPLE-данных)",
        "fx_rate": 1.0,
        "financial_currency": "USD",
        "trading_currency": "USD",
        # No real consensus data for sample runs - compute_forward_outlook
        # falls through its whole chain to the Trailing P/E / Historical FCF
        # CAGR proxies (both computable from the sample data itself) rather
        # than crashing on a missing info dict.
        "info": {},
    }
