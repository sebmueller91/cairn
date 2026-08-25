"""Unit tests for the pure half of calendar-year returns
(performance_service.calendar_year_slices) — no database, per AGENTS.md's
"tests before the feature for anything that calculates".

The whole difficulty of a per-year return table is the boundary: January's
first move has to be measured against 31 December of the *previous* year,
not against its own first day. Getting that wrong silently discards one
day of return per year, which is invisible by eye and compounds.

Invented values only.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.performance_service import FlowEvent, calendar_year_slices, twr


def _dense(start: date, values: list[str]) -> list[tuple[date, Decimal]]:
    return [(start + timedelta(days=i), Decimal(v)) for i, v in enumerate(values)]


def test_empty_series_yields_no_years():
    assert calendar_year_slices([]) == []


def test_single_year_is_returned_whole():
    series = _dense(date(2024, 3, 1), ["100", "110", "120"])
    result = calendar_year_slices(series)
    assert [year for year, _ in result] == [2024]
    assert result[0][1] == series


def test_year_boundary_prepends_previous_year_close():
    # Dec 30, Dec 31, Jan 1, Jan 2 — two calendar years.
    series = _dense(date(2023, 12, 30), ["100", "200", "300", "400"])
    result = calendar_year_slices(series)

    assert [year for year, _ in result] == [2023, 2024]
    # 2023 is its own two days, untouched.
    assert result[0][1] == series[:2]
    # 2024 carries 31 December 2023 in front of it as the base its first
    # daily return is relative to — without it, the 200 -> 300 move on
    # 1 January would belong to no year at all.
    assert result[1][1] == [series[1], series[2], series[3]]


def test_first_year_has_no_prepended_base():
    """Nothing precedes the first year, so its first day has no base and
    contributes no return — the same convention daily_returns already
    uses for a zero opening value."""
    series = _dense(date(2022, 1, 1), ["100", "110"])
    result = calendar_year_slices(series)
    assert result[0][1][0] == (date(2022, 1, 1), Decimal("100"))


def test_slices_partition_every_original_point_exactly_once():
    series = _dense(date(2022, 12, 30), [str(100 + i) for i in range(400)])
    result = calendar_year_slices(series)

    seen: list[tuple[date, Decimal]] = []
    for i, (_, chunk) in enumerate(result):
        # Every chunk after the first opens with a borrowed point.
        seen.extend(chunk[1:] if i > 0 else chunk)
    assert seen == series


def test_chained_year_returns_reproduce_the_whole_period_return():
    """The point of the boundary rule: multiplying the per-year returns
    together must give back the total return over the whole series. If a
    year silently dropped its first day, this identity breaks."""
    series = _dense(date(2022, 12, 31), ["1000", "1100", "1210", "1331", "1464.1"])
    # Days land in 2022 (1) and 2023 (4) — a real year boundary.
    flows: list[FlowEvent] = []

    total = twr(series, flows)
    chained = Decimal(1)
    for _, chunk in calendar_year_slices(series):
        chained *= Decimal(1) + twr(chunk, flows)
    assert float(chained - Decimal(1)) == pytest.approx(float(total), abs=1e-9)


def test_flows_on_new_years_day_are_not_counted_as_return():
    """A contribution on 1 January lands in the borrowed-base window. It
    must still be treated as a flow, not as a 100% overnight gain."""
    series = [
        (date(2023, 12, 31), Decimal("1000")),
        (date(2024, 1, 1), Decimal("2000")),
        (date(2024, 1, 2), Decimal("2200")),
    ]
    flows = [FlowEvent(date(2024, 1, 1), Decimal("1000"))]
    (_, chunk_2024) = calendar_year_slices(series)[1]
    # 1 Jan: (2000 - 1000 - 1000)/1000 = 0. 2 Jan: 200/2000 = +10%.
    assert float(twr(chunk_2024, flows)) == pytest.approx(0.10, abs=1e-9)


def test_gap_years_are_not_invented():
    """A series that genuinely skips a year (no snapshots at all) must
    not have an empty year fabricated between the two real ones — an
    empty year would render as a 0.00% return, which reads as "flat",
    not as "no data"."""
    series = [
        (date(2020, 6, 1), Decimal("100")),
        (date(2022, 6, 1), Decimal("200")),
    ]
    assert [year for year, _ in calendar_year_slices(series)] == [2020, 2022]
