"""Ordinary-company sins checklist (docs/spec/refactor-tasks.md T13,
docs/spec/technical-implementation-spec.md Section 1, and the Ordinary v3
buyback-distortion smart bypasses, docs/spec/step4-ordinary-v3-implementation-spec.md).

Moved verbatim out of compute_metrics() - every input here was already
computed earlier in that function (statement rows found via find_row(),
FX-converted, net_debt computed ahead of this checklist for the Current
Ratio smart-bypass Scenario 2). Sin construction uses fire() against
ORDINARY_SIN_REGISTRY (domain/sins.py, T11) instead of the local
MINOR_SIN_WEIGHTS/BUYBACK_BONUS_WEIGHT/TECHNICAL_*_WEIGHT constants, so
there is one place each weight is defined instead of two.
"""

import pandas as pd

from fundamental_express.domain.sins import ORDINARY_SIN_REGISTRY, fire


def check_ordinary_sins(
    revenue, operating_income, net_income, curr_ratios, equity, fcf,
    gross_margin, operating_margin, net_margin, diluted_shares,
    current_debt, cash, interest_expense, net_debt,
    long_term_assets_adj, long_term_liab,
):
    """Runs every Ordinary critical/minor sin check and returns
    (sins, latest_equity, latest_cr) - the last two are returned because
    compute_metrics() needs them again after this call (latest_equity feeds
    the DCF/DDM valuation, latest_cr feeds the "current_ratio" report
    field)."""
    sins = []

    latest_fcf = fcf.iloc[-1]
    latest_cr = curr_ratios.iloc[-1]
    # Ordinary v3 (Step 4, spec Section 2.1/2.2.1): a stable, mature company
    # can show negative book equity or "long-term insolvency" purely from
    # decades of buybacks (Treasury Stock), not operating distress. Both
    # the equity_negative and lt_insolvency critical sins below check this
    # SAME three-condition proof before being smart-bypassed to a minor sin
    # instead: positive Operating Income and FCF in every available year
    # (up to 4), plus an actively shrinking share count (proof of buyback,
    # not just an assertion).
    buyback_distortion_bypass = (
        len(operating_income) > 0 and bool((operating_income > 0).all())
        and len(fcf) > 0 and bool((fcf > 0).all())
        and not diluted_shares.isna().any()
        and len(diluted_shares) >= 2
        and diluted_shares.iloc[-1] < diluted_shares.iloc[-2]
    )
    # Smart bypass: a Current Ratio below 1.0 driven by, say, deferred revenue
    # or accounts payable isn't the same red flag as an inability to service
    # actual near-term debt. Two independent scenarios grant leniency
    # (Ordinary v3, Step 4 Section 2.2 adds Scenario 2 alongside the
    # original Scenario 1) - either is sufficient on its own:
    #   Scenario 1: FCF-positive and cash alone covers short-term debt.
    #     Never granted on missing current_debt data - leniency requires
    #     proof, not the absence of a red flag.
    #   Scenario 2: FCF-positive, overall leverage is safe (Net Debt /
    #     Operating Income < 4.0 - the 3.0 spec default is raised to 4.0
    #     since Operating Income/EBIT proxies EBITDA and over-penalizes
    #     capital-intensive real-estate-heavy businesses), and interest
    #     coverage is strong (Operating Income / Interest Expense > 4.0 -
    #     an objective proxy for investment-grade debt, since yfinance.info
    #     carries no credit-rating field for virtually any ticker). A
    #     company with no interest-bearing debt at all (Interest Expense
    #     missing/0/NaN) auto-passes the coverage leg - silence there is
    #     never treated as a red flag. Requires a genuine net debt balance
    #     (net_debt > 0): a net-CASH company isn't what this leverage-grade
    #     scenario is for, and it belongs to Scenario 1's territory instead
    #     if it wants credit for having more cash than short-term debt.
    cr_bypass_scenario1 = (
        latest_cr < 1.0
        and latest_fcf > 0
        and not pd.isna(current_debt.iloc[-1])
        and not pd.isna(cash.iloc[-1])
        and cash.iloc[-1] > current_debt.iloc[-1]
    )
    latest_op_inc = operating_income.iloc[-1]
    latest_interest_expense = interest_expense.iloc[-1] if len(interest_expense) else float("nan")
    icr_ok = (
        pd.isna(latest_interest_expense)
        or latest_interest_expense == 0
        or (latest_op_inc / latest_interest_expense) > 4.0
    )
    cr_bypass_scenario2 = (
        latest_cr < 1.0
        and latest_fcf > 0
        and latest_op_inc > 0
        and not pd.isna(net_debt)
        and net_debt > 0
        and (net_debt / latest_op_inc) < 4.0
        and icr_ok
    )
    cr_bypass_eligible = cr_bypass_scenario1 or cr_bypass_scenario2
    if latest_cr < 1.0 and not cr_bypass_eligible:
        sins.append(fire(
            ORDINARY_SIN_REGISTRY, "cr_below_1",
            f"Критическая ликвидность: коэффициент текущей ликвидности (Current Ratio) ниже 1.0 ({latest_cr:.2f}).",
        ))
    elif latest_cr < 1.0 and cr_bypass_eligible:
        reasons = []
        if cr_bypass_scenario1:
            reasons.append(
                f"FCF положительный ({latest_fcf / 1e6:,.0f} млн) и денежные средства "
                f"({cash.iloc[-1] / 1e6:,.0f} млн) превышают краткосрочный долг "
                f"({current_debt.iloc[-1] / 1e6:,.0f} млн)"
            )
        if cr_bypass_scenario2:
            icr_txt = (
                "∞ (процентного долга нет)"
                if pd.isna(latest_interest_expense) or latest_interest_expense == 0
                else f"{latest_op_inc / latest_interest_expense:.2f}"
            )
            reasons.append(
                f"безопасный уровень долговой нагрузки (Net Debt / Operating Income = "
                f"{net_debt / latest_op_inc:.2f}, < 4.0) при сильном покрытии процентов "
                f"(Interest Coverage Ratio = {icr_txt}, > 4.0)"
            )
        sins.append(fire(
            ORDINARY_SIN_REGISTRY, "cr_below_1_bypassed",
            f"Ликвидность ниже 1.0 ({latest_cr:.2f}), но не критична: " + "; ".join(reasons) + ".",
        ))
    # A CR decline is only flagged if the company also isn't comfortably
    # liquid (CR >= 2.0) after the decline - dropping from, say, 4.0 to 3.0
    # isn't a red flag on its own. Requiring latest_cr >= 1.0 here keeps this
    # mutually exclusive with the two branches above - a CR crash below 1.0
    # is already captured (critical or bypassed) and must not also
    # double-count as a minor "declining trend" sin on the same fact.
    elif (
        len(curr_ratios) >= 2
        and curr_ratios.iloc[-1] < curr_ratios.iloc[-2]
        and latest_cr < 2.0
    ):
        sins.append(fire(
            ORDINARY_SIN_REGISTRY, "cr_declining",
            f"Снижающийся тренд ликвидности: Current Ratio с {curr_ratios.iloc[-2]:.2f} до {curr_ratios.iloc[-1]:.2f}.",
        ))

    if long_term_liab is not None:
        latest_lt_assets = long_term_assets_adj.iloc[-1]
        latest_lt_liab = long_term_liab.iloc[-1]
        if latest_lt_assets < latest_lt_liab and buyback_distortion_bypass:
            # Ordinary v3 (Step 4, Section 2.2.1): same buyback-distortion
            # story as equity_negative below - book long-term assets fall
            # under liabilities purely from accumulated Treasury Stock, not
            # from operating distress (proven by the same 3 conditions).
            sins.append(fire(
                ORDINARY_SIN_REGISTRY, "technical_lt_insolvency",
                "Техническая долгосрочная неплатежеспособность в результате активного выкупа акций "
                "(Buyback) при сильной операционной рентабельности.",
            ))
        elif latest_lt_assets < latest_lt_liab:
            sins.append(fire(
                ORDINARY_SIN_REGISTRY, "lt_insolvency",
                f"Долгосрочная неплатёжеспособность: скорректированные (за вычетом Goodwill) "
                f"долгосрочные активы ({latest_lt_assets / 1e6:,.0f} млн) меньше долгосрочных "
                f"обязательств ({latest_lt_liab / 1e6:,.0f} млн).",
            ))

    latest_equity = equity.iloc[-1]
    if latest_equity <= 0 and buyback_distortion_bypass:
        # Ordinary v3 (Step 4, Section 2.1): negative book equity purely
        # from decades of buybacks (Treasury Stock), not operating losses -
        # proven by positive Operating Income/FCF every available year plus
        # an actively shrinking share count (buyback_distortion_bypass).
        sins.append(fire(
            ORDINARY_SIN_REGISTRY, "technical_negative_equity",
            "Технический отрицательный капитал в результате активного выкупа акций (Buyback) при "
            "стабильно сильных операционных и денежных результатах.",
        ))
    elif latest_equity <= 0:
        sins.append(fire(
            ORDINARY_SIN_REGISTRY, "equity_negative",
            "Отрицательный акционерный капитал: обязательств больше, чем реальных активов.",
        ))
    elif len(equity) >= 2 and equity.iloc[-1] < equity.iloc[-2]:
        sins.append(fire(
            ORDINARY_SIN_REGISTRY, "equity_declining",
            "Тренд падения капитала: Shareholder Equity снизился за последний год.",
        ))

    if latest_fcf <= 0:
        sins.append(fire(
            ORDINARY_SIN_REGISTRY, "fcf_negative",
            "Сжигание денежных средств: отрицательный Free Cash Flow.",
        ))
    elif len(fcf) >= 2 and fcf.iloc[-1] < fcf.iloc[-2]:
        sins.append(fire(
            ORDINARY_SIN_REGISTRY, "fcf_declining",
            "Падение денежного потока: снижение FCF за последний год.",
        ))

    if len(revenue) >= 2 and revenue.iloc[-1] < revenue.iloc[-2]:
        sins.append(fire(
            ORDINARY_SIN_REGISTRY, "revenue_declining",
            "Снижение выручки за последний год.",
        ))
    if len(operating_income) >= 2 and operating_income.iloc[-1] < operating_income.iloc[-2]:
        sins.append(fire(
            ORDINARY_SIN_REGISTRY, "operating_income_declining",
            "Падение операционной прибыли за последний год.",
        ))
    if len(net_income) >= 2 and net_income.iloc[-1] < net_income.iloc[-2]:
        sins.append(fire(
            ORDINARY_SIN_REGISTRY, "net_income_declining",
            "Падение чистой прибыли за последний год.",
        ))
    if gross_margin is not None and len(gross_margin) >= 2 and gross_margin.iloc[-1] < gross_margin.iloc[-2]:
        sins.append(fire(
            ORDINARY_SIN_REGISTRY, "gross_margin_declining",
            f"Падение валовой маржи: Gross Margin с {gross_margin.iloc[-2]:.1f}% до {gross_margin.iloc[-1]:.1f}%.",
        ))
    if len(operating_margin) >= 2 and operating_margin.iloc[-1] < operating_margin.iloc[-2]:
        sins.append(fire(
            ORDINARY_SIN_REGISTRY, "operating_margin_declining",
            f"Падение операционной маржи: Operating Margin с {operating_margin.iloc[-2]:.1f}% до {operating_margin.iloc[-1]:.1f}%.",
        ))
    if len(net_margin) >= 2 and net_margin.iloc[-1] < net_margin.iloc[-2]:
        sins.append(fire(
            ORDINARY_SIN_REGISTRY, "net_margin_declining",
            f"Падение рентабельности: чистая маржа с {net_margin.iloc[-2]:.1f}% до {net_margin.iloc[-1]:.1f}%.",
        ))

    # Dilution / buyback bonus: share-count changes economically equivalent
    # to a per-share earnings cut (dilution) or a shareholder-friendly boost
    # (buyback), mutually exclusive since a >1.5% YoY move can only go one
    # direction. Skipped silently if diluted_shares wasn't found for this
    # ticker's statements (default_val=NaN) - never guessed from a partial row.
    if (
        not diluted_shares.isna().any()
        and len(diluted_shares) >= 2
        and diluted_shares.iloc[-2] != 0
    ):
        shares_ratio = diluted_shares.iloc[-1] / diluted_shares.iloc[-2]
        if shares_ratio > 1.015:
            sins.append(fire(
                ORDINARY_SIN_REGISTRY, "dilution",
                f"Размытие долей: средневзвешенное число акций выросло с {diluted_shares.iloc[-2]:,.0f} "
                f"до {diluted_shares.iloc[-1]:,.0f} ({(shares_ratio - 1) * 100:.1f}%).",
            ))
        elif shares_ratio < (1 / 1.015):
            sins.append(fire(
                ORDINARY_SIN_REGISTRY, "buyback_bonus",
                f"Бонус за байбэк: число акций сократилось с {diluted_shares.iloc[-2]:,.0f} "
                f"до {diluted_shares.iloc[-1]:,.0f} ({(1 - shares_ratio) * 100:.1f}%).",
            ))

    return sins, latest_equity, latest_cr
