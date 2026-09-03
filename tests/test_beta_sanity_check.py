"""V08 (docs/spec/issues/V08-beta-sanity-check.md): _sanitize_beta() clamps
Yahoo's raw beta to a plausible range, flagging when it did.
"""

import math

import pytest

from financial_analyzer import compute_metrics
from fundamental_express.data.yahoo import FALLBACK_BETA, _sanitize_beta
from tests.test_ordinary_v3 import make_data


def test_normal_beta_passes_through_untouched():
    assert _sanitize_beta(1.3) == (1.3, False)


def test_none_falls_back():
    assert _sanitize_beta(None) == (FALLBACK_BETA, True)


def test_zero_falls_back_same_as_pre_v08_or_idiom():
    assert _sanitize_beta(0) == (FALLBACK_BETA, True)
    assert _sanitize_beta(0.0) == (FALLBACK_BETA, True)


def test_nan_falls_back():
    beta, is_fallback = _sanitize_beta(float("nan"))
    assert beta == FALLBACK_BETA
    assert is_fallback is True


def test_negative_beta_falls_back():
    assert _sanitize_beta(-2.0) == (FALLBACK_BETA, True)


def test_extremely_high_beta_falls_back():
    assert _sanitize_beta(5.0) == (FALLBACK_BETA, True)


def test_boundary_values_are_kept_not_clamped():
    # -1.0 and 3.0 are inside the inclusive [lo, hi] range - not fallbacks.
    assert _sanitize_beta(-1.0) == (-1.0, False)
    assert _sanitize_beta(3.0) == (3.0, False)


def test_just_outside_boundary_falls_back():
    assert _sanitize_beta(-1.01) == (FALLBACK_BETA, True)
    assert _sanitize_beta(3.01) == (FALLBACK_BETA, True)


def test_non_numeric_falls_back_without_crashing():
    beta, is_fallback = _sanitize_beta("not-a-number")
    assert beta == FALLBACK_BETA
    assert is_fallback is True


# ── Report disclosure (compute_metrics level) ────────────────────────────

def test_report_valuation_carries_beta_is_fallback_flag():
    m = compute_metrics(make_data())
    # make_data() doesn't wire beta through data["beta"] at all by default
    # (financial_analyzer.py's compute_metrics() reads data["beta"]
    # directly, bypassing _sanitize_beta - that only runs in
    # data/yahoo.py's fetch path) - this test locks in that the flag
    # defaults to False when the fetch layer never set it, so a synthetic
    # fixture (or --allow-sample) never shows a spurious warning.
    assert m.valuation.beta_is_fallback is False
