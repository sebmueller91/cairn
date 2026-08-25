"""Forward projection of the wealth curve (spec 4.6's milestone maths,
run forwards instead of solved for time).

This module is different in kind from everything around it, and the
difference matters more than the arithmetic does. Every other number in
this app is derived from a recorded fact — a transaction, a price, a CPI
reading. A projection is an *assumption* rendered as a curve. AGENTS.md's
rule that estimates must never be presented like measurements (the house
index and the car depreciation model already live under it) applies here
with more force than anywhere else, because a smooth exponential is the
most persuasive-looking thing a chart can draw.

Three consequences, all deliberate:

- The model is the one the milestone card already commits to
  (`milestones_service.months_to_reach`): an ordinary annuity, monthly
  compounding, contributions at period end. Not because it is the most
  sophisticated available, but because the app must not hold two
  different opinions about what a savings rate implies. The two are
  pinned together by a test.
- Nothing here picks the assumptions. The return, the spread around it
  and the inflation rate all arrive as parameters; the router's defaults
  are the app's existing ones, not new domain rules invented here.
- Real terms are computed against an *assumed* forward inflation rate,
  never against the CPI series. `real_wealth_service.deflate_series`
  carries the last known index forward, which for a future date silently
  yields a factor of exactly 1.0 — a projected 2036 figure would be
  labelled "in today's money" while being nothing of the kind. That is
  the single most dangerous thing this feature could get wrong, so the
  deflation lives here and takes its rate explicitly.
"""

import calendar
from datetime import date
from decimal import Decimal

# Twelve monthly periods a year, matching months_to_reach's r/12. Stated
# once so the two modules can't drift on the convention.
MONTHS_PER_YEAR = 12


def project_wealth(
    start_value: Decimal,
    monthly_savings: Decimal,
    annual_return_pct: Decimal,
    months: int,
) -> list[tuple[int, Decimal]]:
    """Month-by-month future value: v(n) = v(n-1) * (1 + r) + s, with
    r = annual_return_pct / 100 / 12.

    That recurrence is exactly the closed form months_to_reach inverts —
    (v0 + s/r)(1+r)^n - s/r — so the two agree by construction rather
    than by coincidence.

    Returned as (month_number, value) pairs numbered from 1, so a caller
    can map month numbers onto dates without assuming the list is dense.
    Both `monthly_savings` and `annual_return_pct` may be negative: a
    household can spend more than it saves, and a return assumption is
    allowed to be pessimistic. Neither is clamped — clamping would
    quietly answer a different question than the one asked.
    """
    rate = annual_return_pct / Decimal(100) / Decimal(MONTHS_PER_YEAR)
    out: list[tuple[int, Decimal]] = []
    value = start_value
    for month in range(1, months + 1):
        value = value * (Decimal(1) + rate) + monthly_savings
        out.append((month, value))
    return out


def deflate_projection(
    points: list[tuple[int, Decimal]], annual_inflation_pct: Decimal
) -> list[tuple[int, Decimal]]:
    """Projected values expressed in *today's* purchasing power:
    v / (1 + inflation) ** (months / 12).

    Deliberately not `real_wealth_service.deflate_series` — see this
    module's docstring. Same question, but the past has a measured index
    to divide by and the future does not.

    Each point is deflated by its own month number rather than by its
    position in the list, so a downsampled or sparse series stays
    correct.
    """
    if annual_inflation_pct == 0:
        return list(points)
    base = Decimal(1) + annual_inflation_pct / Decimal(100)
    out: list[tuple[int, Decimal]] = []
    for month, value in points:
        years = Decimal(month) / Decimal(MONTHS_PER_YEAR)
        # Decimal has no fractional power, and this is a presentation-time
        # derived figure rather than stored money, so float is the right
        # tool for the exponent alone (same reasoning performance_service
        # gives for xirr). The result returns to Decimal immediately.
        factor = Decimal(str(float(base) ** float(years)))
        out.append((month, value / factor))
    return out


def add_months(start: date, months: int) -> date:
    """`start` advanced by whole calendar months, clamping to the last day
    of a shorter target month.

    31 January + 1 month has no 31 February to land on. Clamping to the
    28th (or 29th) keeps the projected series strictly increasing;
    rolling forward into 3 March instead would put two projected points
    inside the same month and make the chart's month ticks lie.
    """
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)
