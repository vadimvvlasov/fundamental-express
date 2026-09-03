"""V03 (docs/spec/issues/V03-normalize-nonrecurring-items.md): a one-off
impairment/gain in Net Income must not fire (or hide) the
net_income_declining sin - the sin should track yfinance's own
"Normalized Income" row instead of the raw, unadjusted figure. No such
row present -> pure no-op (byte-identical to pre-V03 behavior).
"""

import pytest

from financial_analyzer import compute_bank_metrics, compute_metrics
from tests.test_bank_analyzer import make_bank_data
from tests.test_ordinary_v3 import make_data, sin_ids


def test_ordinary_declining_sin_does_not_fire_when_only_raw_income_dipped():
    # Reported net income dips in the last year (one-off impairment), but
    # Normalized Income (with the impairment excluded) keeps climbing -
    # the sin must track the normalized trend, not the raw one. Values are
    # dollar-scale (not the small unitless numbers other tests in this
    # file use) because the disclosure note's $1M noise floor
    # (financial_analyzer.py's _nonrecurring_note) is dollar-denominated.
    m = compute_metrics(make_data(
        net_income=(150e6, 160e6, 170e6, 100e6),
        normalized_income=(150e6, 160e6, 170e6, 180e6),
    ))
    assert "net_income_declining" not in sin_ids(m.scoring.sins)
    assert m.nonrecurring_note is not None
    assert "2025" in m.nonrecurring_note


def test_ordinary_declining_sin_still_fires_when_normalized_also_declines():
    m = compute_metrics(make_data(
        net_income=(150.0, 160.0, 170.0, 100.0),
        normalized_income=(150.0, 160.0, 170.0, 120.0),
    ))
    assert "net_income_declining" in sin_ids(m.scoring.sins)


def test_ordinary_reported_table_stays_raw_not_normalized():
    m = compute_metrics(make_data(
        net_income=(150.0, 160.0, 170.0, 100.0),
        normalized_income=(150.0, 160.0, 170.0, 180.0),
    ))
    # The fundamentals table (m.net_income) must still show the reported,
    # unadjusted figure - normalization is internal to the sin check only.
    assert m.net_income.iloc[-1] == 100.0


def test_ordinary_noop_when_no_normalized_income_row():
    with_row = compute_metrics(make_data(net_income=(150.0, 160.0, 170.0, 100.0)))
    assert with_row.nonrecurring_note is None
    assert "net_income_declining" in sin_ids(with_row.scoring.sins)


def test_ordinary_noop_when_normalized_income_matches_raw():
    m = compute_metrics(make_data(
        net_income=(150.0, 160.0, 170.0, 180.0),
        normalized_income=(150.0, 160.0, 170.0, 180.0),
    ))
    assert m.nonrecurring_note is None


def test_ordinary_sub_million_difference_is_not_disclosed_as_an_adjustment():
    # Rounding-noise-sized gap (< $1M) must not trigger a disclosure line.
    m = compute_metrics(make_data(
        net_income=(150.0, 160.0, 170.0, 180.0),
        normalized_income=(150.0, 160.0, 170.0, 180.5),
    ))
    assert m.nonrecurring_note is None


def test_ordinary_normalized_income_nan_for_one_year_falls_back_to_raw_that_year():
    # "Row present, blank for one year" (NaN) must not be treated as "row
    # not found" for the years it DOES cover.
    m = compute_metrics(make_data(
        net_income=(150.0, 160.0, 170.0, 100.0),
        normalized_income=(150.0, 160.0, float("nan"), 180.0),
    ))
    assert "net_income_declining" not in sin_ids(m.scoring.sins)


# ── Bank path ─────────────────────────────────────────────────────────

def test_bank_declining_sin_does_not_fire_when_only_raw_income_dipped():
    m = compute_bank_metrics(make_bank_data(
        net_income=(150e6, 150e6, 150e6, 90e6),
        normalized_income=(150e6, 150e6, 150e6, 160e6),
    ))
    assert "net_income_declining" not in sin_ids(m.scoring.sins)
    assert m.nonrecurring_note is not None


def test_bank_noop_when_no_normalized_income_row():
    m = compute_bank_metrics(make_bank_data(net_income=(150.0, 150.0, 150.0, 90.0)))
    assert m.nonrecurring_note is None
    assert "net_income_declining" in sin_ids(m.scoring.sins)


def test_bank_reported_table_and_roe_stay_raw():
    m = compute_bank_metrics(make_bank_data(
        cash_dividends_paid=None, dividend_yield=0.0,
        net_income=(150.0, 150.0, 150.0, 90.0),
        normalized_income=(150.0, 150.0, 150.0, 160.0),
    ))
    assert m.net_income.iloc[-1] == 90.0
    assert m.roe == pytest.approx(90.0 / 1000.0)
