"""Financial-statement parsing helpers shared by every domain engine
(Ordinary/Bank/REIT): locating a row by keyword, and aligning three
statements (financials/balance/cashflow) onto their common year columns.
Moved verbatim out of financial_analyzer.py (docs/spec/refactor-tasks.md T06).
"""

import pandas as pd


# ── ROBUST FINANCIAL ROW LOCATOR ────────────────────────────────────────
def find_row(df, keywords, default_val=0.0):
    """Find a financial statement row by keyword.

    Exact matches across ALL keywords are tried before ANY partial match.
    yfinance's row order commonly puts lines like "Reconciled Cost Of
    Revenue" ahead of "Total Revenue" - checking exact matches per-keyword
    before moving on (the old behavior) let a "revenue" partial match grab
    the cost-of-revenue row before "total revenue" ever got its exact-match
    turn, silently corrupting margin/revenue-trend numbers downstream.
    """
    for kw in keywords:
        for idx in df.index:
            if kw.lower() == idx.lower():
                return df.loc[idx]
    for kw in keywords:
        for idx in df.index:
            if kw.lower() in idx.lower():
                return df.loc[idx]
    # Return series of zeros with same columns
    return pd.Series([default_val] * len(df.columns), index=df.columns)


def _align_statement_years(df_fin, df_bal, df_cf):
    """Sort financials/balance/cashflow by year and restrict all three to
    the years common to all of them.

    compute_metrics() (Ordinary, untouched) uses a simpler pattern: sort by
    the income statement's own years, then reindex balance/cashflow to that
    same list. That silently breaks whenever a bank or REIT's balance sheet
    or cashflow statement reports one fewer year than its income statement
    (observed live for JPM - financials has 4 years, cashflow 5; and for
    PLD - financials has 5 years, balance only 4): reindexing with a column
    that doesn't exist raises KeyError, the bare except swallows it, and
    financials ends up sorted while balance/cashflow silently stay in their
    original most-recent-first order - every .iloc[-1]/.iloc[-2] YoY
    comparison sourced from balance/cashflow then reads the wrong year
    without any visible error. Restricting to the common intersection
    avoids that failure mode entirely, at the cost of dropping a year that
    only one of the three statements reports (unusable for YoY math anyway
    since the other two statements have nothing to compare it against).
    """
    common = set(df_fin.columns) & set(df_bal.columns) & set(df_cf.columns)
    try:
        years_sorted = sorted(common, key=lambda x: int(str(x).split("-")[0]))
    except Exception:
        years_sorted = sorted(common, key=str)
    if not years_sorted:
        # No shared years at all (pathological data) - fall back to the
        # income statement's own columns rather than producing empty frames.
        years_sorted = list(df_fin.columns)
    year_labels = [str(y).split("-")[0] for y in years_sorted]
    try:
        return df_fin[years_sorted], df_bal[years_sorted], df_cf[years_sorted], year_labels
    except KeyError:
        # Pathological fallback above still didn't line up with bal/cf -
        # return the frames completely unsorted rather than crashing; every
        # find_row() default/NaN-guard downstream still applies.
        return df_fin, df_bal, df_cf, [str(y).split("-")[0] for y in df_fin.columns]
