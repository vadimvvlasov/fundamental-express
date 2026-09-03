"""V10 (docs/spec/issues/V10-graham-number-reproducible.md): Graham Number
as a real, reproducible code path - depends on V01's tangible_equity for
tangible BVPS (not raw, goodwill-inflated equity).
"""

import math

import pytest

from financial_analyzer import compute_bank_metrics, compute_metrics
from fundamental_express.domain.graham import eps_for_graham, graham_number
from tests.test_bank_analyzer import make_bank_data
from tests.test_ordinary_v3 import make_data


# ── graham_number() unit tests ───────────────────────────────────────────

def test_graham_number_matches_hand_computed_value():
    # sqrt(22.5 * 5.0 * 40.0) = sqrt(4500) = 67.0820...
    assert graham_number(5.0, 40.0) == pytest.approx(math.sqrt(4500.0))


def test_graham_number_none_for_negative_eps():
    assert graham_number(-1.0, 40.0) is None


def test_graham_number_none_for_zero_or_negative_bvps():
    assert graham_number(5.0, 0.0) is None
    assert graham_number(5.0, -10.0) is None


def test_graham_number_none_for_nan_inputs():
    assert graham_number(float("nan"), 40.0) is None
    assert graham_number(5.0, float("nan")) is None


def test_graham_number_none_for_none_inputs():
    assert graham_number(None, 40.0) is None
    assert graham_number(5.0, None) is None


# ── eps_for_graham() unit tests ──────────────────────────────────────────

def test_eps_for_graham_prefers_trailing_eps_when_present():
    value, label = eps_for_graham({"trailingEps": 6.5}, latest_annual_eps=5.0)
    assert value == pytest.approx(6.5)
    assert label == "ttm"


def test_eps_for_graham_falls_back_to_annual_eps():
    value, label = eps_for_graham({}, latest_annual_eps=5.0)
    assert value == pytest.approx(5.0)
    assert label == "FY"


def test_eps_for_graham_falls_back_when_trailing_eps_is_nan():
    value, label = eps_for_graham({"trailingEps": float("nan")}, latest_annual_eps=5.0)
    assert value == pytest.approx(5.0)
    assert label == "FY"


def test_eps_for_graham_handles_none_info():
    value, label = eps_for_graham(None, latest_annual_eps=5.0)
    assert value == pytest.approx(5.0)
    assert label == "FY"


# ── compute_metrics() / compute_bank_metrics() wiring ────────────────────

def test_ordinary_graham_uses_tangible_bvps_not_raw():
    # equity=2000, goodwill=1200 -> tangible_equity=800, shares=100 -> tangible bvps=8.0
    # eps=2.0 (make_data default) -> graham = sqrt(22.5*2.0*8.0) = sqrt(360)
    m = compute_metrics(make_data(
        equity=(2000.0, 2000.0, 2000.0, 2000.0),
        goodwill=(1200.0, 1200.0, 1200.0, 1200.0),
    ))
    assert m.graham_tangible_bvps == pytest.approx(8.0)
    assert m.graham_value == pytest.approx(math.sqrt(22.5 * 2.0 * 8.0))


def test_ordinary_graham_none_when_eps_non_positive():
    m = compute_metrics(make_data(eps=(2.0, 2.0, 2.0, -1.0)))
    assert m.graham_value is None


def test_ordinary_graham_uses_annual_eps_label_by_default():
    m = compute_metrics(make_data())
    assert m.graham_eps_label == "FY"


def test_bank_graham_uses_tangible_bvps():
    m = compute_bank_metrics(make_bank_data(
        cash_dividends_paid=None, dividend_yield=0.0,
        shareholders_equity=(1000.0, 1000.0, 1000.0, 1000.0),
        goodwill=(400.0, 400.0, 400.0, 400.0),
    ))
    # tangible_equity = 1000-400=600, shares=100 -> tangible bvps=6.0
    assert m.graham_tangible_bvps == pytest.approx(6.0)


def test_graham_never_influences_sins_or_verdict():
    # Same fixture (equity held fixed, well within the D/E-distress
    # threshold either way), only goodwill - and therefore only the
    # Graham Number - differs. Sins/verdict must be identical.
    no_goodwill = compute_metrics(make_data(goodwill=(0.0, 0.0, 0.0, 0.0)))
    with_goodwill = compute_metrics(make_data(goodwill=(50.0, 50.0, 50.0, 50.0)))
    assert no_goodwill.graham_value != with_goodwill.graham_value
    assert no_goodwill.scoring.verdict == with_goodwill.scoring.verdict
    assert [s.id for s in no_goodwill.scoring.sins] == [s.id for s in with_goodwill.scoring.sins]
