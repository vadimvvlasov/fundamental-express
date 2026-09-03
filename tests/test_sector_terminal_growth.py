"""V09 (docs/spec/issues/V09-sector-terminal-growth.md): terminal growth
is sector-bucketed instead of a flat 2.5% for every company. An unmatched
sector/industry must resolve to exactly 2.5% - the pre-V09 flat rate -
so this is a byte-identical no-op for anything that doesn't match a bucket.
"""

import pytest

from financial_analyzer import compute_bank_metrics, compute_metrics
from tests.test_bank_analyzer import make_bank_data
from tests.test_ordinary_v3 import make_data


def test_unmatched_sector_resolves_to_pre_v09_default():
    # "Consumer Cyclical" alone doesn't match any bucket keyword.
    m = compute_metrics(make_data(industry="Apparel Retail", sector="Consumer Cyclical"))
    assert m.terminal_g == pytest.approx(0.025)
    assert m.terminal_g_label == "Default"


def test_utilities_gets_lower_terminal_growth():
    m = compute_metrics(make_data(industry="Utilities—Regulated Electric", sector="Utilities"))
    assert m.terminal_g == pytest.approx(0.015)
    assert "Utilities" in m.terminal_g_label


def test_technology_gets_higher_terminal_growth():
    m = compute_metrics(make_data(industry="Software—Application", sector="Technology"))
    assert m.terminal_g == pytest.approx(0.030)


def test_bank_terminal_growth_matches_sector_bucket_too():
    m = compute_bank_metrics(make_bank_data(
        cash_dividends_paid=(-50.0, -50.0, -50.0, -50.0), dividend_yield=0.02,
    ))
    assert m.terminal_g == pytest.approx(0.025)  # default fixture sector unmatched
    assert m.terminal_g_label == "Default"
