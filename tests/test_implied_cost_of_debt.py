"""V05 (docs/spec/issues/V05-implied-cost-of-debt.md): Kd derived from the
company's own Interest Expense / Debt when available, clamped to
[2%, 12%], falling back to the flat 4.5% when data is missing.
"""

import pytest

from financial_analyzer import compute_metrics
from tests.test_ordinary_v3 import make_data


def test_implied_kd_used_when_interest_expense_available():
    # 45 / 1000 = 4.5% - deliberately picked to overlap the fallback value,
    # so the label (not the number) is what distinguishes the two paths.
    m = compute_metrics(make_data(
        long_term_debt=(1000.0, 1000.0, 1000.0, 1000.0),
        interest_expense=(45.0, 45.0, 45.0, 45.0),
    ))
    assert bool(m.cost_of_debt_is_implied) is True
    assert m.cost_of_debt == pytest.approx(0.045)


def test_fallback_kd_used_when_no_interest_expense_row():
    m = compute_metrics(make_data(long_term_debt=(1000.0, 1000.0, 1000.0, 1000.0)))
    assert bool(m.cost_of_debt_is_implied) is False
    assert m.cost_of_debt == pytest.approx(0.045)


def test_implied_kd_clamped_to_ceiling():
    m = compute_metrics(make_data(
        long_term_debt=(100.0, 100.0, 100.0, 100.0),
        interest_expense=(50.0, 50.0, 50.0, 50.0),  # 50/100 = 50%, way above ceiling
    ))
    assert bool(m.cost_of_debt_is_implied) is True
    assert m.cost_of_debt == pytest.approx(0.12)


def test_implied_kd_clamped_to_floor():
    m = compute_metrics(make_data(
        long_term_debt=(1000.0, 1000.0, 1000.0, 1000.0),
        interest_expense=(1.0, 1.0, 1.0, 1.0),  # 0.1%, below floor
    ))
    assert bool(m.cost_of_debt_is_implied) is True
    assert m.cost_of_debt == pytest.approx(0.02)


def test_fallback_used_when_debt_is_zero():
    m = compute_metrics(make_data(
        long_term_debt=(0.0, 0.0, 0.0, 0.0),
        interest_expense=(5.0, 5.0, 5.0, 5.0),
    ))
    assert bool(m.cost_of_debt_is_implied) is False
    assert m.cost_of_debt == pytest.approx(0.045)
