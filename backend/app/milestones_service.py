"""Milestones (spec 4.6): "the next round number, and time to reach it at
the current savings rate and an assumed return."
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal

from sqlalchemy.orm import Session

from app.attribution_service import _buy_sell_delta, _cash_delta
from app.models import DailySnapshot

_STEP_MULTIPLIERS = (Decimal(1), Decimal(2), Decimal(5))


def next_round_number(current_value: Decimal) -> Decimal:
    """Smallest "nice" number (a 1/2/5 x a power of ten — the same
    sequence chart-axis tick generators use) strictly greater than
    current_value. Deliberately skips non-nice values (150k, 300k, ...):
    a milestone is meant to be a number worth celebrating, not every
    possible round-ish figure."""
    if current_value <= 0:
        return Decimal(1000)
    magnitude = current_value.log10().to_integral_value(rounding=ROUND_FLOOR)
    power = Decimal(10) ** magnitude
    for _ in range(4):
        for m in _STEP_MULTIPLIERS:
            candidate = m * power
            if candidate > current_value:
                return candidate
        power *= 10
    return current_value  # unreachable at any realistic wealth magnitude


def months_to_reach(
    current_value: Decimal,
    target_value: Decimal,
    monthly_savings: Decimal,
    annual_return_pct: Decimal,
) -> float | None:
    """Months to grow current_value into target_value, contributing
    monthly_savings each month and compounding at annual_return_pct/12
    monthly — the standard future-value-of-a-growing-annuity formula,
    solved for time instead of final value. None when it's genuinely
    unreachable (no growth assumed and nothing being saved), not a
    fabricated number."""
    if current_value >= target_value:
        return 0.0
    r = float(annual_return_pct) / 100.0 / 12.0
    v0 = float(current_value)
    s = float(monthly_savings)
    t = float(target_value)

    if r == 0:
        return (t - v0) / s if s > 0 else None

    denom = v0 + s / r
    numer = t + s / r
    if denom <= 0 or numer <= 0:
        return None
    x = numer / denom
    if x <= 1:
        return 0.0 if s > 0 else None
    return math.log(x) / math.log(1 + r)


def trailing_12mo_savings_rate(db: Session, as_of: date | None = None) -> Decimal:
    """Average monthly net contribution over the trailing 12 months —
    the same flow definition attribution_service.py uses (cash-account
    deltas + BUY/SELL into MARKET positions), reused rather than
    redefined a third time in this codebase."""
    as_of = as_of or date.today()
    start = as_of - timedelta(days=365)
    total_flow = _cash_delta(db, start, as_of) + _buy_sell_delta(db, start, as_of)
    return total_flow / Decimal(12)


@dataclass
class MilestoneResult:
    scope: str
    current_value_eur: Decimal
    next_milestone_eur: Decimal
    monthly_savings_eur: Decimal
    assumed_annual_return_pct: Decimal
    months_to_reach: float | None
    estimated_date: date | None


def compute_milestone(
    db: Session,
    scope: str = "net",
    assumed_annual_return_pct: Decimal = Decimal(5),
    as_of: date | None = None,
) -> MilestoneResult:
    as_of = as_of or date.today()
    row = (
        db.query(DailySnapshot)
        .filter(DailySnapshot.scope_type == "total", DailySnapshot.scope_id == scope)
        .order_by(DailySnapshot.date.desc())
        .first()
    )
    current_value = row.value_eur if row else Decimal(0)
    target = next_round_number(current_value)
    monthly_savings = trailing_12mo_savings_rate(db, as_of)
    months = months_to_reach(current_value, target, monthly_savings, assumed_annual_return_pct)
    estimated_date = as_of + timedelta(days=round(months * 30.44)) if months is not None else None

    return MilestoneResult(
        scope=scope,
        current_value_eur=current_value,
        next_milestone_eur=target,
        monthly_savings_eur=monthly_savings,
        assumed_annual_return_pct=assumed_annual_return_pct,
        months_to_reach=months,
        estimated_date=estimated_date,
    )
