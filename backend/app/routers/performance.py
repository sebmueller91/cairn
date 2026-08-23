from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import get_scope
from app.database import get_db
from app.performance_query import (
    InvalidPeriodError,
    InvalidScopeError,
    benchmark_price_series,
    flow_events,
    inception_date,
    latest_snapshot_date,
    parse_scope,
    period_start,
    value_series,
)
from app.performance_service import (
    cumulative_index,
    daily_returns,
    mwr,
    shadow_value_series,
    twr,
)
from app.schemas import PerformancePoint, PerformanceResponse

router = APIRouter(prefix="/api/performance", tags=["performance"])


@router.get("", response_model=PerformanceResponse)
def get_performance(
    scope: str = "total",
    period: str = "1Y",
    method: str = "twr",
    benchmark_instrument_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> PerformanceResponse:
    try:
        scope_filter = parse_scope(scope)
    except InvalidScopeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_scope", "params": {"scope": scope}},
        ) from None
    if method not in ("twr", "mwr"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_method", "params": {"method": method}},
        )

    # The daily_snapshot table only extends through the last nightly
    # rebuild — between midnight and that job's 23:00 run, date.today()
    # names a day with no snapshot rows at all. Reading that as
    # Decimal(0) (value_series' documented mid-series convention) would
    # be wrong here: it's not a real zero, it's staleness. Clamp to
    # whatever the engine has actually produced instead.
    end = date.today()
    latest = latest_snapshot_date(db)
    if latest is not None and latest < end:
        end = latest
    inception = inception_date(db, scope_filter)
    try:
        start = period_start(period, end, inception)
    except InvalidPeriodError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_period", "params": {"period": period}},
        ) from None
    if inception is not None and start < inception:
        start = inception

    values = value_series(db, scope_filter, start, end)
    flows = flow_events(db, scope_filter, start, end)

    if method == "twr":
        returns = daily_returns(values, flows)
        curve = [
            PerformancePoint(date=d, index_value=float(v))
            for d, v in cumulative_index(returns)
        ]
        return_pct = float(twr(values, flows)) if returns else None

        benchmark_curve = None
        if benchmark_instrument_id is not None:
            dates = [d for d, _ in values]
            prices = benchmark_price_series(db, benchmark_instrument_id, dates)
            shadow_values = shadow_value_series(dates, flows, prices)
            shadow_returns = daily_returns(shadow_values, flows)
            benchmark_curve = [
                PerformancePoint(date=d, index_value=float(v))
                for d, v in cumulative_index(shadow_returns)
            ]

        return PerformanceResponse(
            scope=scope,
            period=period,
            method=method,
            start_date=start,
            end_date=end,
            return_pct=return_pct,
            curve=curve,
            benchmark_curve=benchmark_curve,
        )

    # Bug fix: `flow_events` treats `start` inclusively (same convention
    # TWR needs, see its docstring there), so any flow dated exactly on
    # `start` — e.g. `period="inception"` resolving to the very first
    # transaction's own date, which is *every* inception window — shows
    # up both here (if start_value came from `values[0]`, the snapshot
    # ON `start`, which already reflects that day's trade) AND again in
    # `flows` below, double-counting day one's investment as two
    # separate outflows. `mwr()`'s contract is that `start_value` is the
    # implicit outflow that funded the position *before* any of `flows`
    # happened — so it must come from the day *before* `start`, not from
    # `start` itself. At true inception that's zero (nothing existed
    # yet), which is exactly right: the whole opening position then
    # enters once, correctly, via the first flow.
    pre_start = start - timedelta(days=1)
    pre_start_values = value_series(db, scope_filter, pre_start, pre_start)
    start_value = pre_start_values[0][1] if pre_start_values else None
    end_value = values[-1][1] if values else None
    if start_value is None or end_value is None:
        return PerformanceResponse(
            scope=scope, period=period, method=method,
            start_date=start, end_date=end, return_pct=None, curve=None,
        )
    rate = mwr(start, start_value, flows, end, end_value)
    return PerformanceResponse(
        scope=scope,
        period=period,
        method=method,
        start_date=start,
        end_date=end,
        return_pct=rate,
        curve=None,
    )
