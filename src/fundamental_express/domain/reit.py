"""REIT sins checklist (docs/spec/refactor-tasks.md T15,
docs/spec/step3-reit-analyzer-implementation-spec.md Section 4).

Moved verbatim out of compute_reit_metrics() - every input here was
already computed earlier in that function (statement rows found via
find_row(), FX-converted, FFO/AFFO/NOI derived). Sin construction uses
fire() against REIT_SIN_REGISTRY (domain/sins.py, T11) instead of the
local REIT_MINOR_SIN_WEIGHTS/REIT_BUYBACK_BONUS_WEIGHT constants, which
are retired.

Unlike Bank, a critical hit here does NOT interrupt minor scoring (spec
Section 4 has no "interrupts detailed scoring" language for REIT) - minor
sins are always computed in full, same as Ordinary.
"""

import pandas as pd

from fundamental_express.domain.sins import REIT_SIN_REGISTRY, fire


def check_reit_sins(dividends_paid, affo, occupancy_rate, shareholders_equity, diluted_shares, total_debt, noi, capex, ffo):
    """Runs every REIT critical/minor sin check and returns
    (sins, affo_payout_ratio, debt_to_equity) - both are needed again by
    compute_reit_metrics() after this call (they feed the report
    directly; unlike Ordinary/Bank, REIT's NAV valuation needs neither
    latest_equity nor a cost of equity, so nothing else has to come back)."""
    latest_equity = shareholders_equity.iloc[-1]
    latest_affo = affo.iloc[-1]
    latest_dividends = dividends_paid.iloc[-1] if not pd.isna(dividends_paid.iloc[-1]) else 0.0

    # ── Section 4.1: Critical sins ───────────────────────────────────────
    sins = []
    affo_payout_ratio = None
    if latest_dividends > 0:
        if latest_affo <= 0:
            affo_payout_ratio = float("inf")
            sins.append(fire(
                REIT_SIN_REGISTRY, "affo_payout_over_100",
                f"Дивиденды «в долг»: выплачены дивиденды ({latest_dividends / 1e6:,.0f} млн) при "
                f"AFFO ≤ 0 ({latest_affo / 1e6:,.0f} млн) - выплата не обеспечена денежным потоком.",
            ))
        else:
            affo_payout_ratio = latest_dividends / latest_affo
            if affo_payout_ratio > 1.0:
                sins.append(fire(
                    REIT_SIN_REGISTRY, "affo_payout_over_100",
                    f"Дивиденды «в долг»: AFFO Payout Ratio = {affo_payout_ratio * 100:.1f}% (> 100%) - "
                    "траст выплачивает больше, чем зарабатывает по AFFO.",
                ))
    if occupancy_rate < 0.80:
        sins.append(fire(
            REIT_SIN_REGISTRY, "occupancy_below_80",
            f"Низкая заполняемость объектов: Occupancy Rate = {occupancy_rate * 100:.1f}% (< 80%).",
        ))
    if not pd.isna(latest_equity) and latest_equity <= 0:
        sins.append(fire(
            REIT_SIN_REGISTRY, "equity_negative",
            f"Отрицательный акционерный капитал: Shareholders Equity ({latest_equity / 1e6:,.0f} млн) ≤ 0.",
        ))
    critical_sins = [s for s in sins if s.tier == "critical"]

    # ── Section 4.2: Minor sins (always computed - no interruption here) ─
    if len(affo) >= 2 and affo.iloc[-2] > 0 and affo.iloc[-1] > 0 and affo.iloc[-1] < affo.iloc[-2]:
        sins.append(fire(
            REIT_SIN_REGISTRY, "affo_declining",
            f"Падение AFFO: с {affo.iloc[-2] / 1e6:,.0f} до {affo.iloc[-1] / 1e6:,.0f} млн.",
        ))
    # Note: occupancy_declining (spec Section 4.2) is not evaluated here -
    # occupancy_rate above is a single current-snapshot value (yfinance
    # carries no historical Occupancy Rate time series), so there is no
    # prior-year figure to compare against without inventing one.
    debt_to_equity = None
    if (
        not diluted_shares.isna().any()
        and len(diluted_shares) >= 2
        and diluted_shares.iloc[-2] != 0
    ):
        shares_ratio = diluted_shares.iloc[-1] / diluted_shares.iloc[-2]
        if shares_ratio > 1.025:
            sins.append(fire(
                REIT_SIN_REGISTRY, "dilution",
                f"Размытие капитала через SPO: среднее число акций выросло с {diluted_shares.iloc[-2]:,.0f} "
                f"до {diluted_shares.iloc[-1]:,.0f} ({(shares_ratio - 1) * 100:.1f}%).",
            ))
        elif shares_ratio < (1 / 1.015):
            sins.append(fire(
                REIT_SIN_REGISTRY, "buyback_bonus",
                f"Бонус за байбэк: число акций сократилось с {diluted_shares.iloc[-2]:,.0f} "
                f"до {diluted_shares.iloc[-1]:,.0f} ({(1 - shares_ratio) * 100:.1f}%).",
            ))
    if not pd.isna(latest_equity) and latest_equity > 0 and not pd.isna(total_debt.iloc[-1]):
        debt_to_equity = total_debt.iloc[-1] / latest_equity
        if debt_to_equity > 2.0:
            sins.append(fire(
                REIT_SIN_REGISTRY, "high_leverage",
                f"Критический долг: Total Debt / Shareholders Equity = {debt_to_equity * 100:.1f}% (> 200%).",
            ))
    if len(noi) >= 2 and noi.iloc[-1] < noi.iloc[-2]:
        sins.append(fire(
            REIT_SIN_REGISTRY, "noi_declining",
            f"Падение NOI: с {noi.iloc[-2] / 1e6:,.0f} до {noi.iloc[-1] / 1e6:,.0f} млн.",
        ))
    if len(capex) >= 2 and len(ffo) >= 2 and ffo.iloc[-2] > 0 and ffo.iloc[-1] > 0:
        capex_ratio_prior = capex.iloc[-2].__abs__() / ffo.iloc[-2]
        capex_ratio_current = capex.iloc[-1].__abs__() / ffo.iloc[-1]
        if capex_ratio_prior > 0 and (capex_ratio_current / capex_ratio_prior - 1) > 0.05:
            sins.append(fire(
                REIT_SIN_REGISTRY, "capex_ratio_growth",
                f"Рост доли капинвестиций: CapEx/FFO вырос с {capex_ratio_prior * 100:.1f}% до "
                f"{capex_ratio_current * 100:.1f}% (YoY > 5%).",
            ))

    return sins, affo_payout_ratio, debt_to_equity
