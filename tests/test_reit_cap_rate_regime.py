"""V06 (docs/spec/issues/V06-reit-cap-rate-rate-regime.md): REIT cap rates
are spreads over the shared RF_RATE constant, not standalone hardcoded
percentages - changing RF_RATE moves them.
"""

import pytest

from financial_analyzer import compute_reit_metrics
import fundamental_express.domain.valuation as valuation_module
from tests.test_reit_analyzer import make_reit_data


def test_default_cap_rate_matches_pre_v06_hardcoded_value_at_default_rf():
    m = compute_reit_metrics(make_reit_data())
    assert m.cap_rate == pytest.approx(0.065)  # 2.5% spread + 4.0% Rf


def test_industrial_keyword_cap_rate_matches_pre_v06_hardcoded_value():
    m = compute_reit_metrics(make_reit_data(info={"industry": "Industrial REIT"}))
    assert m.cap_rate == pytest.approx(0.055)  # 1.5% spread + 4.0% Rf


def test_changing_rf_rate_moves_the_reit_cap_rate(monkeypatch):
    monkeypatch.setattr(valuation_module, "RF_RATE", 0.06)
    m = compute_reit_metrics(make_reit_data())
    assert m.cap_rate == pytest.approx(0.085)  # 2.5% spread + 6.0% Rf (moved)


def test_cap_rate_label_discloses_spread_and_rf_composition():
    m = compute_reit_metrics(make_reit_data(info={"industry": "Industrial REIT"}))
    assert "1.5%" in m.cap_rate_label
    assert "4.0%" in m.cap_rate_label


def test_explicit_info_cap_rate_still_bypasses_the_matrix_entirely():
    m = compute_reit_metrics(make_reit_data(info={"capRate": 0.08}))
    assert m.cap_rate == pytest.approx(0.08)
    assert m.cap_rate_label == "Explicit (info.capRate)"
