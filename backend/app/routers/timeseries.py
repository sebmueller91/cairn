from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_scope
from app.database import get_db
from app.models import CpiIndexPoint, DailySnapshot, Instrument
from app.real_wealth_service import deflate_series
from app.schemas import AllocationTimeseriesPoint, NetWorthPoint

router = APIRouter(prefix="/api/timeseries", tags=["timeseries"])


def _period_key(d: date, granularity: str) -> tuple:
    if granularity == "week":
        year, week, _ = d.isocalendar()
        return (year, week)
    if granularity == "month":
        return (d.year, d.month)
    return (d.year, d.month, d.day)


@router.get("/networth", response_model=list[NetWorthPoint])
def get_networth_timeseries(
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    granularity: str = "day",
    # spec 4.1's three notions of wealth. Defaults to 'investable' — the
    # allocation view's own default perspective (spec 4.1: "if the house
    # is 60% of total wealth, an equity share of 18% of total wealth
    # isn't actionable"), not an arbitrary choice.
    scope: str = "investable",
    # spec 4.6: the same curve, additionally adjusted for inflation —
    # "what would this be worth in today's money." A query param on the
    # existing endpoint rather than a new one, so period/granularity/scope
    # all keep working exactly the same way.
    real: bool = False,
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> list[NetWorthPoint]:
    query = db.query(DailySnapshot).filter(
        DailySnapshot.scope_type == "total", DailySnapshot.scope_id == scope
    )
    if from_ is not None:
        query = query.filter(DailySnapshot.date >= from_)
    if to is not None:
        query = query.filter(DailySnapshot.date <= to)
    rows = query.order_by(DailySnapshot.date).all()

    if granularity == "day":
        selected = rows
    else:
        # Last day of data within each period represents that period —
        # downsampling is what keeps a 10-year chart from refolding
        # thousands of daily rows on every request (ADR 0004).
        last_per_period: dict[tuple, DailySnapshot] = {}
        for row in rows:
            last_per_period[_period_key(row.date, granularity)] = row
        selected = sorted(last_per_period.values(), key=lambda r: r.date)

    values = [(r.date, r.value_eur) for r in selected]
    if real:
        cpi_points = [
            (p.date, p.index_value)
            for p in db.query(CpiIndexPoint).order_by(CpiIndexPoint.date).all()
        ]
        values = deflate_series(values, cpi_points)

    return [NetWorthPoint(date=d, value_eur=v) for d, v in values]


@router.get("/allocation", response_model=list[AllocationTimeseriesPoint])
def get_allocation_timeseries(
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    granularity: str = "day",
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> list[AllocationTimeseriesPoint]:
    """Net worth decomposed by asset class over time — the per-class
    sibling of /networth (spec's allocation-over-time view)."""
    query = db.query(DailySnapshot).filter(
        DailySnapshot.scope_type.in_(["position", "cash_account", "loan"])
    )
    if from_ is not None:
        query = query.filter(DailySnapshot.date >= from_)
    if to is not None:
        query = query.filter(DailySnapshot.date <= to)
    rows = query.order_by(DailySnapshot.date).all()

    if granularity == "day":
        kept_dates = {r.date for r in rows}
    else:
        # Downsample by date first (mirroring /networth's "last day of
        # data represents the period"), then aggregate only rows that
        # fall on a kept date — a date, not a single row, is the unit
        # here since several scope rows share the same date.
        last_per_period: dict[tuple, date] = {}
        for d in {r.date for r in rows}:
            key = _period_key(d, granularity)
            if key not in last_per_period or d > last_per_period[key]:
                last_per_period[key] = d
        kept_dates = set(last_per_period.values())

    # Load every instrument once, keyed by id -> asset_class. Unlike
    # allocation_service.current_allocation (MARKET-only, since that's for
    # rebalancing tradeable positions), this deliberately includes every
    # valuation mode — ANCHORED houses and MODELED cars must still show up
    # under REAL_ESTATE/VEHICLE, because this endpoint feeds net-worth
    # decomposition, not a buy/sell proposal.
    instruments = {i.id: i.asset_class.value for i in db.query(Instrument).all()}

    by_date: dict[date, dict[str, Decimal]] = {}
    for row in rows:
        if row.date not in kept_dates:
            continue
        buckets = by_date.setdefault(row.date, {})
        if row.scope_type == "position":
            instrument_id = int(row.scope_id.split(":")[1])
            key = instruments.get(instrument_id)
            if key is None:
                continue
        elif row.scope_type == "cash_account":
            key = "CASH"
        else:  # loan — value_eur is already negative, pass through unchanged
            key = "LIABILITY"
        buckets[key] = buckets.get(key, Decimal(0)) + row.value_eur

    return [
        AllocationTimeseriesPoint(date=d, values=by_date[d])
        for d in sorted(by_date)
    ]
