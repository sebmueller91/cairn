"""Unit tests for the projection maths (projection_service.py) — no
database, per AGENTS.md's "tests before the feature for anything that
calculates".

A projection is the only figure in this app that is not derived from a
recorded fact, so the bar is not "does it produce a number" but "is it
the *same* model the rest of the app already commits to". The test that
matters most here is the one pinning it to milestones_service: those two
must never disagree about what a given savings rate and return imply.

Invented values only.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.milestones_service import months_to_reach
from app.projection_service import add_months, deflate_projection, project_wealth


# --- project_wealth -------------------------------------------------------


def test_no_growth_and_no_savings_stays_flat():
    result = project_wealth(Decimal(1000), Decimal(0), Decimal(0), 6)
    assert [v for _, v in result] == [Decimal(1000)] * 6


def test_no_growth_accumulates_savings_linearly():
    result = project_wealth(Decimal(1000), Decimal(100), Decimal(0), 3)
    assert [v for _, v in result] == [Decimal(1100), Decimal(1200), Decimal(1300)]


def test_no_savings_compounds_the_return():
    # 12% a year is 1% a month here — the same monthly-compounding
    # convention months_to_reach uses, not an annualised equivalent.
    result = project_wealth(Decimal(1000), Decimal(0), Decimal(12), 2)
    assert result[0][1] == pytest.approx(Decimal("1010"), abs=Decimal("0.01"))
    assert result[1][1] == pytest.approx(Decimal("1020.10"), abs=Decimal("0.01"))


def test_months_are_numbered_from_one():
    result = project_wealth(Decimal(1000), Decimal(10), Decimal(0), 3)
    assert [m for m, _ in result] == [1, 2, 3]


def test_zero_horizon_projects_nothing():
    assert project_wealth(Decimal(1000), Decimal(100), Decimal(5), 0) == []


def test_a_negative_return_shrinks_the_pot():
    result = project_wealth(Decimal(1000), Decimal(0), Decimal(-12), 1)
    assert result[0][1] == pytest.approx(Decimal("990"), abs=Decimal("0.01"))


def test_a_negative_savings_rate_draws_down():
    """A household spending more than it puts in is a real state — the
    trailing savings rate is a measured figure and can be negative. It
    must project a decline, not be clamped to zero."""
    result = project_wealth(Decimal(1000), Decimal(-100), Decimal(0), 3)
    assert [v for _, v in result] == [Decimal(900), Decimal(800), Decimal(700)]


def test_agrees_with_months_to_reach():
    """The load-bearing test.

    `months_to_reach` (spec 4.6, already shipped in the milestone card)
    solves the growing-annuity formula for time. This projects the same
    annuity forward for a given time. They are the same model read in
    two directions, so projecting N months and asking how long that took
    must give back N. If someone later "fixes" the compounding
    convention in one of them, the milestone card and the projection
    would quietly start telling the user different things.
    """
    v0, savings, rate = Decimal(50000), Decimal(750), Decimal(6)
    projected = project_wealth(v0, savings, rate, 60)
    for months in (12, 36, 60):
        target = projected[months - 1][1]
        assert months_to_reach(v0, target, savings, rate) == pytest.approx(
            float(months), abs=1e-6
        )


def test_exactness_is_preserved_through_decimal():
    """Money stays Decimal end to end (AGENTS.md). A float would make the
    sum of a long horizon drift in the last cents, which is exactly the
    kind of silent error this codebase refuses elsewhere."""
    result = project_wealth(Decimal("1000.00"), Decimal("0.10"), Decimal(0), 3)
    assert all(isinstance(v, Decimal) for _, v in result)
    assert result[-1][1] == Decimal("1000.30")


# --- deflate_projection ---------------------------------------------------


def test_zero_inflation_leaves_the_projection_untouched():
    points = [(12, Decimal(1000)), (24, Decimal(2000))]
    assert deflate_projection(points, Decimal(0)) == points


def test_one_year_of_inflation_divides_by_one_plus_the_rate():
    points = [(12, Decimal(1050))]
    result = deflate_projection(points, Decimal(5))
    assert result[0][1] == pytest.approx(Decimal(1000), abs=Decimal("0.01"))


def test_deflation_compounds_over_years():
    points = [(24, Decimal(1000))]
    result = deflate_projection(points, Decimal(10))
    # 1000 / 1.1^2
    assert result[0][1] == pytest.approx(Decimal("826.45"), abs=Decimal("0.01"))


def test_a_return_matching_inflation_projects_flat_in_real_terms():
    """The point of showing real terms at all: 5% nominal growth against
    5% inflation is not growth. If this ever reads as a rising line, the
    real view is lying in the most consequential way it can."""
    projected = project_wealth(Decimal(10000), Decimal(0), Decimal(5), 120)
    real = deflate_projection(projected, Decimal(5))
    # Monthly compounding at 5%/12 slightly outruns annual compounding at
    # 5%, so this drifts a little rather than sitting exactly flat — the
    # tolerance is that drift, not slop.
    assert float(real[-1][1]) == pytest.approx(10000, rel=0.02)


def test_deflation_is_indexed_by_month_not_position():
    """Points carry their own month number; a sparse list must deflate by
    that number, not by where it happens to sit in the list."""
    dense = deflate_projection([(1, Decimal(1000)), (12, Decimal(1000))], Decimal(10))
    sparse = deflate_projection([(12, Decimal(1000))], Decimal(10))
    assert dense[1][1] == sparse[0][1]


# --- add_months -----------------------------------------------------------


def test_add_months_walks_the_calendar():
    assert add_months(date(2026, 1, 15), 1) == date(2026, 2, 15)
    assert add_months(date(2026, 1, 15), 12) == date(2027, 1, 15)
    assert add_months(date(2026, 11, 15), 2) == date(2027, 1, 15)


def test_add_months_clamps_to_the_end_of_a_shorter_month():
    """31 January plus one month has no 31 February to land on. Clamping
    keeps the series strictly increasing; rolling into March would put
    two projected points in the same month."""
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)  # leap year
    assert add_months(date(2026, 3, 31), 1) == date(2026, 4, 30)


def test_add_months_produces_a_strictly_increasing_series():
    start = date(2026, 1, 31)
    dates = [add_months(start, n) for n in range(1, 25)]
    assert all(a < b for a, b in zip(dates, dates[1:]))
