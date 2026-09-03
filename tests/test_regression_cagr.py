"""V02 (docs/spec/issues/V02-regression-cagr.md): unit tests for
_regression_cagr() directly - the multi-year log-linear regression that
replaced the old endpoint-to-endpoint CAGR formula in
domain/valuation.py's FCF/dividend growth calculations.
"""

import pytest

from fundamental_express.domain.valuation import _regression_cagr


def test_two_point_degenerates_to_old_endpoint_formula():
    # Old formula: (v1/v0)**(1/1) - 1 == v1/v0 - 1
    v0, v1 = 100.0, 150.0
    expected = v1 / v0 - 1
    got = _regression_cagr([v0, v1], lo=-1.0, hi=10.0, default=0.05)
    assert got == pytest.approx(expected, rel=1e-9)


def test_two_point_degenerates_for_declining_series_too():
    v0, v1 = 200.0, 120.0
    expected = v1 / v0 - 1
    got = _regression_cagr([v0, v1], lo=-1.0, hi=10.0, default=0.05)
    assert got == pytest.approx(expected, rel=1e-9)


def test_outlier_year_moves_result_materially_vs_endpoint_formula():
    # Years 2-4 show a clean, flat trend; year 1 and year 5 are outliers
    # in opposite directions. Endpoint formula reads only 100 -> 100
    # (0% growth). Regression should see the actual trend from the middle
    # years and land well away from 0%, by more than 1 percentage point.
    values = [40.0, 100.0, 105.0, 110.0, 100.0]
    endpoint_cagr = (values[-1] / values[0]) ** (1 / (len(values) - 1)) - 1
    regression_cagr = _regression_cagr(values, lo=-1.0, hi=10.0, default=0.05)
    assert abs(regression_cagr - endpoint_cagr) > 0.01


def test_negative_value_inside_window_falls_back_to_default():
    # Old endpoint formula only ever looked at values[0]/values[-1] and
    # would have happily computed a CAGR here (both positive) - the
    # regression must catch the non-positive value hiding in the middle.
    got = _regression_cagr([100.0, 50.0, -10.0, 120.0], lo=-1.0, hi=10.0, default=0.05)
    assert got == 0.05


def test_zero_value_inside_window_falls_back_to_default():
    got = _regression_cagr([100.0, 0.0, 110.0], lo=-1.0, hi=10.0, default=0.03)
    assert got == 0.03


def test_fewer_than_two_values_falls_back_to_default():
    assert _regression_cagr([100.0], lo=-1.0, hi=10.0, default=0.05) == 0.05
    assert _regression_cagr([], lo=-1.0, hi=10.0, default=0.05) == 0.05


def test_result_is_clamped_to_bounds():
    # Explosive growth, way outside any of this codebase's clamp ranges.
    got = _regression_cagr([1.0, 100.0], lo=0.02, hi=0.15, default=0.05)
    assert got == pytest.approx(0.15)
    # Steep decline, clamped to the floor.
    got = _regression_cagr([100.0, 1.0], lo=0.02, hi=0.15, default=0.05)
    assert got == pytest.approx(0.02)


def test_flat_series_yields_zero_growth_before_clamp():
    got = _regression_cagr([50.0, 50.0, 50.0, 50.0], lo=-1.0, hi=1.0, default=0.05)
    assert got == pytest.approx(0.0, abs=1e-9)
