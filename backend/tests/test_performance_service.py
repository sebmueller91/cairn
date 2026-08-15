from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.performance_service import (
    FlowEvent,
    chain_link,
    cumulative_index,
    daily_returns,
    mwr,
    shadow_value_series,
    twr,
    xirr,
)


def test_daily_returns_simple_growth_no_flows():
    values = [(date(2026, 1, 1), Decimal(1000)), (date(2026, 1, 2), Decimal(1100))]
    returns = daily_returns(values, [])
    assert returns == [(date(2026, 1, 2), Decimal("0.1"))]


def test_twr_chains_multiple_days():
    # Day 1: +10%, day 2: +10% again, on the new base -> (1.1*1.1)-1 = 0.21
    values = [
        (date(2026, 1, 1), Decimal(1000)),
        (date(2026, 1, 2), Decimal(1100)),
        (date(2026, 1, 3), Decimal(1210)),
    ]
    assert twr(values, []) == Decimal("0.21")


def test_twr_excludes_a_deposit_funded_buy():
    # Day0 V=1000. Day1: organic growth to 1050 (+5%) plus a fresh 500
    # BUY landing the same day -> V(day1) = 1550, flow(day1) = +500.
    # TWR should read the pure 5% market move, not the capital injection.
    values = [(date(2026, 1, 1), Decimal(1000)), (date(2026, 1, 2), Decimal(1550))]
    flows = [FlowEvent(date(2026, 1, 2), Decimal(500))]
    assert twr(values, flows) == Decimal("0.05")


def test_twr_a_sell_with_no_market_move_is_zero_return():
    # Day0 V=1000. Day1: sell exactly 300 worth, no price movement on the
    # remainder -> V(day1) = 700, flow(day1) = -300. Selling your own
    # money out shouldn't itself register as a loss.
    values = [(date(2026, 1, 1), Decimal(1000)), (date(2026, 1, 2), Decimal(700))]
    flows = [FlowEvent(date(2026, 1, 2), Decimal(-300))]
    assert twr(values, flows) == Decimal(0)


def test_twr_skips_days_starting_from_zero():
    # Nothing invested yet on day0 (V=0) -> the first day-pair is skipped
    # rather than producing a division by zero or a bogus "infinite" return.
    values = [
        (date(2026, 1, 1), Decimal(0)),
        (date(2026, 1, 2), Decimal(1000)),  # first BUY, funded entirely by flow
        (date(2026, 1, 3), Decimal(1100)),
    ]
    flows = [FlowEvent(date(2026, 1, 2), Decimal(1000))]
    returns = daily_returns(values, flows)
    # Only the day2 -> day3 pair produces a return (day1 -> day2 is
    # skipped because v0 == 0).
    assert returns == [(date(2026, 1, 3), Decimal("0.1"))]
    assert twr(values, flows) == Decimal("0.1")


def test_chain_link_matches_manual_product():
    returns = [
        (date(2026, 1, 2), Decimal("0.1")),
        (date(2026, 1, 3), Decimal("-0.05")),
    ]
    expected = (Decimal("1.1") * Decimal("0.95")) - Decimal(1)
    assert chain_link(returns) == expected


def test_cumulative_index_starts_at_base_and_compounds():
    returns = [
        (date(2026, 1, 2), Decimal("0.1")),
        (date(2026, 1, 3), Decimal("0.1")),
    ]
    curve = cumulative_index(returns, base=Decimal(100))
    assert curve == [
        (date(2026, 1, 2), Decimal("110.0")),
        (date(2026, 1, 3), Decimal("121.00")),
    ]


def test_xirr_single_flow_exact_one_year_20_percent():
    # Invest 1000, get back 1200 exactly 365 days later -> NPV(rate) =
    # -1000 + 1200/(1+rate)^1 = 0 at rate = 0.2 exactly, a clean
    # hand-computable case since the day-count basis is also 365.
    d0 = date(2026, 1, 1)
    d1 = d0 + timedelta(days=365)
    result = xirr([(d0, Decimal(-1000)), (d1, Decimal(1200))])
    assert result == pytest.approx(0.2, abs=1e-6)


def test_xirr_multiple_flows_solves_npv_to_zero():
    # No clean closed form with a mid-period flow — verify the fundamental
    # XIRR equation (NPV at the solved rate is ~0) instead of trusting a
    # separately hand-derived rate, which is the more rigorous check here.
    d0 = date(2026, 1, 1)
    d_mid = d0 + timedelta(days=182)
    d_end = d0 + timedelta(days=365)
    cashflows = [(d0, Decimal(-1000)), (d_mid, Decimal(-500)), (d_end, Decimal(1600))]
    rate = xirr(cashflows)
    assert rate is not None
    npv = sum(
        float(amt) / (1.0 + rate) ** (float((d - d0).days) / 365.0)
        for d, amt in cashflows
    )
    assert npv == pytest.approx(0.0, abs=1e-4)


def test_xirr_requires_both_signs():
    assert xirr([(date(2026, 1, 1), Decimal(-1000)), (date(2026, 6, 1), Decimal(-200))]) is None
    assert xirr([(date(2026, 1, 1), Decimal(1000))]) is None


def test_shadow_value_series_single_contribution():
    d1, d2, d3 = date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)
    dates = [d1, d2, d3]
    flows = [FlowEvent(d1, Decimal(1000))]
    prices = {d1: Decimal(100), d2: Decimal(100), d3: Decimal(110)}
    series = shadow_value_series(dates, flows, prices)
    assert series == [
        (d1, Decimal(1000)),  # 10 units @ 100
        (d2, Decimal(1000)),  # no move
        (d3, Decimal(1100)),  # 10 units @ 110
    ]


def test_shadow_value_series_two_contributions_mirrors_own_flow_schedule():
    d1, d2, d3 = date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)
    dates = [d1, d2, d3]
    flows = [FlowEvent(d1, Decimal(1000)), FlowEvent(d2, Decimal(500))]
    prices = {d1: Decimal(100), d2: Decimal(100), d3: Decimal(110)}
    series = shadow_value_series(dates, flows, prices)
    assert series == [
        (d1, Decimal(1000)),  # 10 units
        (d2, Decimal(1500)),  # +5 units from the 500 contribution -> 15 units @ 100
        (d3, Decimal(1650)),  # 15 units @ 110
    ]


def test_shadow_value_series_missing_price_reads_as_zero():
    d1, d2 = date(2026, 1, 1), date(2026, 1, 2)
    series = shadow_value_series(
        [d1, d2], [FlowEvent(d1, Decimal(1000))], {d1: Decimal(100)}
    )
    assert series == [(d1, Decimal(1000)), (d2, Decimal(0))]


def test_mwr_wraps_start_and_end_value_as_implicit_flows():
    d0 = date(2026, 1, 1)
    d1 = d0 + timedelta(days=365)
    # Start with nothing, deposit 1000 at start, no flows in between, end
    # at 1200 a year later -> same as the single-flow xirr case above.
    rate = mwr(d0, Decimal(0), [FlowEvent(d0, Decimal(1000))], d1, Decimal(1200))
    assert rate == pytest.approx(0.2, abs=1e-6)
