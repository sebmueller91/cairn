from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_scope
from app.database import get_db
from app.models import DailySnapshot
from app.schemas import NetWorthPoint

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
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> list[NetWorthPoint]:
    # Only the 'investable' total exists until phase 5 adds house/car/loan
    # and with them the gross/net perspectives from spec 4.1.
    query = db.query(DailySnapshot).filter(
        DailySnapshot.scope_type == "total", DailySnapshot.scope_id == "investable"
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

    return [NetWorthPoint(date=r.date, value_eur=r.value_eur) for r in selected]
