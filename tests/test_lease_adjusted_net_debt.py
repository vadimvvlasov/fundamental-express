"""V04 (docs/spec/issues/V04-lease-adjusted-net-debt.md): lease-inclusive
net debt is always computed as a secondary fair value, and becomes the
headline "Справедливая стоимость акции" only for a lease-heavy sector.
"""

import pytest

from financial_analyzer import compute_metrics
from tests.test_ordinary_v3 import make_data


def test_lease_inclusive_secondary_value_computed_for_non_lease_heavy_sector():
    m = compute_metrics(make_data(
        long_term_debt=(500.0, 500.0, 500.0, 500.0),
        lease_liabilities=(300.0, 300.0, 300.0, 300.0),
        industry="Software", sector="Technology",
    ))
    # Headline stays the lease-excluded number - not a lease-heavy sector.
    assert m.valuation.fair_value_share == pytest.approx(m.fair_value_share_excl_leases)
    assert m.fair_value_share_incl_leases is not None
    # More debt (lease-inclusive) -> lower equity value -> lower fair value.
    assert m.fair_value_share_incl_leases < m.valuation.fair_value_share
    assert m.lease_heavy_sector is False


def test_lease_inclusive_value_becomes_headline_for_lease_heavy_sector():
    m = compute_metrics(make_data(
        long_term_debt=(500.0, 500.0, 500.0, 500.0),
        lease_liabilities=(300.0, 300.0, 300.0, 300.0),
        industry="Specialty Retail", sector="Consumer Cyclical",
    ))
    assert m.lease_heavy_sector is True
    assert m.valuation.fair_value_share == pytest.approx(m.fair_value_share_incl_leases)
    # Secondary figure (excl leases) still present and higher.
    assert m.fair_value_share_excl_leases is not None
    assert m.fair_value_share_excl_leases > m.valuation.fair_value_share


def test_lease_heavy_sector_with_zero_lease_liabilities_is_a_true_noop():
    m = compute_metrics(make_data(
        lease_liabilities=(0.0, 0.0, 0.0, 0.0),
        industry="Airlines", sector="Industrials",
    ))
    assert m.lease_heavy_sector is True
    assert m.fair_value_share_incl_leases == pytest.approx(m.fair_value_share_excl_leases)
    assert m.valuation.fair_value_share == pytest.approx(m.fair_value_share_excl_leases)


def test_no_lease_data_available_leaves_secondary_figure_none():
    m = compute_metrics(make_data(industry="Specialty Retail", sector="Consumer Cyclical"))
    assert m.fair_value_share_incl_leases is None
    # Headline untouched - can't promote a figure that couldn't be computed,
    # even for a lease-heavy sector, when there's no lease data to compute it from.
    assert m.valuation.valuation_model == "DCF"
    assert m.valuation.fair_value_share == pytest.approx(m.fair_value_share_excl_leases)


def test_ddm_path_has_no_lease_inclusive_figure():
    # DDM has no EV/net_debt concept to re-net - must stay None even with
    # lease data present.
    m = compute_metrics(make_data(
        equity=(-50.0, -60.0, -70.0, -80.0),
        cash_dividends_paid=(-200.0, -210.0, -220.0, -230.0),
        diluted_shares=(110.0, 108.0, 104.0, 100.0),
        dividend_yield=0.03,
        lease_liabilities=(300.0, 300.0, 300.0, 300.0),
        industry="Specialty Retail",
    ))
    assert m.valuation.valuation_model == "DDM"
    assert m.fair_value_share_incl_leases is None
