"""Bank sins checklist (docs/spec/refactor-tasks.md T14,
docs/spec/step2-bank-analyzer-implementation-spec.md Section 4).

Moved verbatim out of compute_bank_metrics() - every input here was
already computed earlier in that function (statement rows found via
find_row(), FX-converted). Sin construction uses fire() against
BANK_SIN_REGISTRY (domain/sins.py, T11) instead of the local
BANK_MINOR_SIN_WEIGHTS/BANK_BUYBACK_BONUS_WEIGHT constants, which are
retired.

Unlike Ordinary, a critical hit here interrupts minor scoring entirely
(spec Section 4.1/4.2) - the `if not critical_sins:` gate below is
preserved exactly as it reads in compute_bank_metrics() today.
"""

import pandas as pd

from fundamental_express.domain.sins import BANK_SIN_REGISTRY, fire


def check_bank_sins(
    net_interest_income, shareholders_equity, credit_loss_provision,
    diluted_shares, net_loans, total_deposits, cash_and_equiv,
    non_interest_expense, commissions_income, net_income, total_borrowings,
):
    """Runs every Bank critical/minor sin check and returns
    (sins, latest_equity, ltd_ratio, debt_to_equity) - all three are
    needed again by compute_bank_metrics() after this call (latest_equity
    feeds the DDM/ROE-P-B valuation, ltd_ratio/debt_to_equity feed the
    report directly)."""
    latest_nii = net_interest_income.iloc[-1]
    latest_equity = shareholders_equity.iloc[-1]

    # ── Section 4.1: Critical sins (any one -> immediate SKIP) ──────────
    sins = []
    if not pd.isna(latest_nii) and latest_nii <= 0:
        sins.append(fire(
            BANK_SIN_REGISTRY, "nii_non_positive",
            f"Чистый процентный убыток: NII последнего года ({latest_nii / 1e6:,.0f} млн) ≤ 0 - "
            "банк привлекает депозиты дороже, чем размещает кредиты.",
        ))
    if not pd.isna(latest_equity) and latest_equity <= 0:
        sins.append(fire(
            BANK_SIN_REGISTRY, "equity_negative",
            f"Отрицательный регуляторный капитал: Shareholders Equity ({latest_equity / 1e6:,.0f} млн) ≤ 0 - "
            "угроза немедленного отзыва лицензии регулятором.",
        ))
    critical_sins = [s for s in sins if s.tier == "critical"]

    # ── Section 4.2: Minor sins ──────────────────────────────────────────
    # Per spec: any critical hit interrupts the detailed minor scoring, so
    # minor sins are only evaluated when no critical sin fired.
    ltd_ratio = None
    debt_to_equity = None
    if not critical_sins:
        if len(net_interest_income) >= 2 and net_interest_income.iloc[-1] < net_interest_income.iloc[-2]:
            sins.append(fire(
                BANK_SIN_REGISTRY, "nii_declining",
                f"Падение процентного дохода: NII с {net_interest_income.iloc[-2] / 1e6:,.0f} до "
                f"{net_interest_income.iloc[-1] / 1e6:,.0f} млн.",
            ))
        if (
            len(credit_loss_provision) >= 2
            and credit_loss_provision.iloc[-1] > 1.15 * credit_loss_provision.iloc[-2]
        ):
            sins.append(fire(
                BANK_SIN_REGISTRY, "provision_spike",
                f"Опасный рост резервов: Provision for Credit Losses вырос с "
                f"{credit_loss_provision.iloc[-2] / 1e6:,.0f} до {credit_loss_provision.iloc[-1] / 1e6:,.0f} млн "
                "(YoY > 15%).",
            ))
        if (
            not diluted_shares.isna().any()
            and len(diluted_shares) >= 2
            and diluted_shares.iloc[-2] != 0
        ):
            shares_ratio = diluted_shares.iloc[-1] / diluted_shares.iloc[-2]
            if shares_ratio > 1.015:
                sins.append(fire(
                    BANK_SIN_REGISTRY, "dilution",
                    f"Размытие долей акционеров: среднее число акций выросло с {diluted_shares.iloc[-2]:,.0f} "
                    f"до {diluted_shares.iloc[-1]:,.0f} ({(shares_ratio - 1) * 100:.1f}%).",
                ))
            elif shares_ratio < (1 / 1.015):
                sins.append(fire(
                    BANK_SIN_REGISTRY, "buyback_bonus",
                    f"Бонус за байбэк: число акций сократилось с {diluted_shares.iloc[-2]:,.0f} "
                    f"до {diluted_shares.iloc[-1]:,.0f} ({(1 - shares_ratio) * 100:.1f}%).",
                ))
        latest_loans = net_loans.iloc[-1] if len(net_loans) else float("nan")
        latest_deposits = total_deposits.iloc[-1] if len(total_deposits) else float("nan")
        if not pd.isna(latest_loans) and not pd.isna(latest_deposits) and latest_deposits != 0:
            ltd_ratio = latest_loans / latest_deposits
            if ltd_ratio > 1.0 or ltd_ratio < 0.6:
                sins.append(fire(
                    BANK_SIN_REGISTRY, "ltd_imbalance",
                    f"Дисбаланс Loan-to-Deposit: LTD = {ltd_ratio * 100:.1f}% "
                    f"({'выше 100%, риск дефицита ликвидности' if ltd_ratio > 1.0 else 'ниже 60%, пассивная работа с депозитами'}).",
                ))
        if (
            len(cash_and_equiv) >= 2 and len(net_loans) >= 2
            and not pd.isna(cash_and_equiv.iloc[-1]) and not pd.isna(cash_and_equiv.iloc[-2])
            and not pd.isna(net_loans.iloc[-1]) and not pd.isna(net_loans.iloc[-2])
            and cash_and_equiv.iloc[-1] > 1.30 * cash_and_equiv.iloc[-2]
            and net_loans.iloc[-1] < net_loans.iloc[-2]
        ):
            sins.append(fire(
                BANK_SIN_REGISTRY, "dead_cash",
                f"Накопление мёртвого кэша: денежные средства выросли с {cash_and_equiv.iloc[-2] / 1e6:,.0f} "
                f"до {cash_and_equiv.iloc[-1] / 1e6:,.0f} млн (>+30%), при этом кредитный портфель сократился.",
            ))
        net_op_income = net_interest_income + commissions_income
        if (
            len(non_interest_expense) >= 2 and len(net_op_income) >= 2
            and non_interest_expense.iloc[-2] != 0 and net_op_income.iloc[-2] != 0
        ):
            opex_growth = non_interest_expense.iloc[-1] / non_interest_expense.iloc[-2] - 1
            net_op_income_growth = net_op_income.iloc[-1] / net_op_income.iloc[-2] - 1
            if opex_growth > net_op_income_growth:
                sins.append(fire(
                    BANK_SIN_REGISTRY, "negative_jaws",
                    f"Отрицательный JAWS: операционные расходы выросли на {opex_growth * 100:.1f}%, "
                    f"опережая рост NII+комиссий ({net_op_income_growth * 100:.1f}%).",
                ))
        if len(commissions_income) >= 2 and commissions_income.iloc[-1] < commissions_income.iloc[-2]:
            sins.append(fire(
                BANK_SIN_REGISTRY, "commissions_declining",
                f"Падение комиссионных доходов: с {commissions_income.iloc[-2] / 1e6:,.0f} до "
                f"{commissions_income.iloc[-1] / 1e6:,.0f} млн.",
            ))
        if len(net_income) >= 2 and net_income.iloc[-1] < net_income.iloc[-2]:
            sins.append(fire(
                BANK_SIN_REGISTRY, "net_income_declining",
                f"Падение чистой прибыли: с {net_income.iloc[-2] / 1e6:,.0f} до "
                f"{net_income.iloc[-1] / 1e6:,.0f} млн.",
            ))
        if not pd.isna(latest_equity) and latest_equity > 0 and not pd.isna(total_borrowings.iloc[-1]):
            debt_to_equity = total_borrowings.iloc[-1] / latest_equity

    return sins, latest_equity, ltd_ratio, debt_to_equity
