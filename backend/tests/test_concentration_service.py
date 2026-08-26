"""Unit tests for the concentration maths (spec 4.4: "top-10 positions as
a share, HHI concentration index, largest single-stock weight") — no
database, per AGENTS.md.

Invented values only.
"""

from decimal import Decimal

import pytest

from app.concentration_service import (
    effective_holdings,
    herfindahl_index,
    largest_share,
    top_n_share,
)


# --- herfindahl_index -----------------------------------------------------


def test_hhi_of_a_single_holding_is_the_maximum():
    """One position is 100% of itself: 100^2 = 10000, the top of the
    scale. Any concentration measure that doesn't return its maximum here
    is measuring something else."""
    assert herfindahl_index([Decimal(500)]) == pytest.approx(10000, abs=1e-6)


def test_hhi_of_n_equal_holdings_is_ten_thousand_over_n():
    for n in (2, 4, 10, 25):
        values = [Decimal(100)] * n
        assert herfindahl_index(values) == pytest.approx(10000 / n, abs=1e-6)


def test_hhi_is_scale_invariant():
    """It is a function of the shares, not the amounts — doubling every
    holding must not move it."""
    a = herfindahl_index([Decimal(100), Decimal(300), Decimal(600)])
    b = herfindahl_index([Decimal(200), Decimal(600), Decimal(1200)])
    assert a == pytest.approx(b, abs=1e-9)


def test_hhi_rises_as_weight_concentrates():
    spread = herfindahl_index([Decimal(250)] * 4)
    lopsided = herfindahl_index([Decimal(700), Decimal(100), Decimal(100), Decimal(100)])
    assert lopsided > spread


def test_hhi_of_nothing_is_none_not_zero():
    """Zero is the *least* concentrated reading a scale like this has, so
    returning it for "no holdings" would render an empty portfolio as
    perfectly diversified."""
    assert herfindahl_index([]) is None


def test_hhi_of_a_worthless_portfolio_is_none():
    """Shares of a zero total are undefined, not zero."""
    assert herfindahl_index([Decimal(0), Decimal(0)]) is None


# --- top_n_share / largest_share ------------------------------------------


def test_top_n_share_takes_the_largest_regardless_of_input_order():
    values = [Decimal(10), Decimal(500), Decimal(90), Decimal(400)]
    # 500 + 400 out of 1000.
    assert top_n_share(values, 2) == pytest.approx(0.9, abs=1e-9)


def test_top_n_share_of_more_than_exists_is_everything():
    values = [Decimal(300), Decimal(700)]
    assert top_n_share(values, 10) == pytest.approx(1.0, abs=1e-9)


def test_top_n_share_of_nothing_is_none():
    assert top_n_share([], 10) is None
    assert top_n_share([Decimal(0)], 10) is None


def test_largest_share_is_the_biggest_single_weight():
    values = [Decimal(10), Decimal(500), Decimal(90), Decimal(400)]
    assert largest_share(values) == pytest.approx(0.5, abs=1e-9)


def test_largest_share_of_one_holding_is_everything():
    assert largest_share([Decimal(42)]) == pytest.approx(1.0, abs=1e-9)


# --- effective_holdings ---------------------------------------------------


def test_effective_holdings_counts_equal_positions_exactly():
    """10000/HHI is the readable companion to the index: ten equal
    holdings really are ten effective holdings."""
    assert effective_holdings([Decimal(100)] * 10) == pytest.approx(10.0, abs=1e-6)


def test_effective_holdings_discounts_a_dominant_position():
    """Twenty holdings, but one of them is most of the money — the honest
    answer is much nearer one than twenty."""
    values = [Decimal(9000)] + [Decimal(1000) / Decimal(19)] * 19
    result = effective_holdings(values)
    assert result is not None
    assert 1.0 < result < 2.0


def test_effective_holdings_of_nothing_is_none():
    assert effective_holdings([]) is None
