from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import get_scope
from app.database import get_db
from dataclasses import replace as dataclass_replace

from app.performance_query import (
    InvalidAssetClassError,
    InvalidPeriodError,
    InvalidScopeError,
    ScopeFilter,
    benchmark_price_series,
    flow_events,
    flow_events_by_instrument,
    inception_date,
    inception_dates_by_instrument,
    latest_snapshot_date,
    parse_asset_classes,
    parse_scope,
    period_start,
    value_series,
    value_series_by_instrument,
)
from app.performance_service import (
    calendar_year_slices,
    chain_link,
    cumulative_index,
    daily_returns,
    mwr,
    shadow_value_series,
    twr,
)
from app.models import Instrument
from app.schemas import (
    CalendarYearReturnRead,
    CalendarYearsResponse,
    InstrumentReturnRead,
    InstrumentReturnsResponse,
    PerformancePoint,
    PerformanceResponse,
)

router = APIRouter(prefix="/api/performance", tags=["performance"])


@router.get("", response_model=PerformanceResponse)
def get_performance(
    scope: str = "total",
    period: str = "1Y",
    method: str = "twr",
    benchmark_instrument_id: int | None = Query(default=None),
    # Comma-separated AssetClass names, e.g. "EQUITY,BOND". Absent means
    # the whole portfolio. Orthogonal to `scope` on purpose — narrowing
    # to one account and narrowing to one asset class are independent
    # questions, and the interesting one ("my equities, wherever they
    # sit, against MSCI World") needs them combinable.
    asset_classes: str | None = Query(default=None),
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
    try:
        classes = parse_asset_classes(asset_classes)
    except InvalidAssetClassError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_asset_class", "params": {"asset_classes": str(exc)}},
        ) from None
    scope_filter = dataclass_replace(scope_filter, asset_classes=classes)
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

    # What the scope was already worth the day before the window opened.
    # Both branches need it and for the same reason — it is the position
    # that existed before any flow in `flows` — so it is computed once
    # here rather than twice with two chances to get the off-by-one
    # wrong. `flow_events` includes flows dated exactly on `start`, so
    # this must come from the day before; see mwr's note below.
    pre_start = start - timedelta(days=1)
    pre_start_values = value_series(db, scope_filter, pre_start, pre_start)
    start_value = pre_start_values[0][1] if pre_start_values else None

    if method == "twr":
        returns = daily_returns(values, flows)
        curve = [
            PerformancePoint(date=d, index_value=float(v))
            for d, v in cumulative_index(returns)
        ]
        return_pct = float(twr(values, flows)) if returns else None

        benchmark_curve = None
        benchmark_return_pct = None
        if benchmark_instrument_id is not None:
            dates = [d for d, _ in values]
            prices = benchmark_price_series(db, benchmark_instrument_id, dates)
            shadow_values = shadow_value_series(
                dates, flows, prices, opening_value=start_value or Decimal(0)
            )
            shadow_returns = daily_returns(shadow_values, flows)
            benchmark_curve = [
                PerformancePoint(date=d, index_value=float(v))
                for d, v in cumulative_index(shadow_returns)
            ]
            # Chained the same way as the portfolio's own figure, not
            # read off the curve's last point — same input, same
            # function, so the two numbers are guaranteed comparable.
            benchmark_return_pct = (
                float(chain_link(shadow_returns)) if shadow_returns else None
            )

        return PerformanceResponse(
            scope=scope,
            period=period,
            method=method,
            start_date=start,
            end_date=end,
            return_pct=return_pct,
            curve=curve,
            benchmark_curve=benchmark_curve,
            benchmark_return_pct=benchmark_return_pct,
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


def _parsed_asset_classes(raw: str | None):
    try:
        return parse_asset_classes(raw)
    except InvalidAssetClassError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_asset_class", "params": {"asset_classes": str(exc)}},
        ) from None


def _window_end(db: Session) -> date:
    """Today, clamped to whatever the nightly snapshot rebuild has
    actually materialised — see latest_snapshot_date's note on why
    date.today() is staleness in disguise every morning."""
    end = date.today()
    latest = latest_snapshot_date(db)
    if latest is not None and latest < end:
        end = latest
    return end


@router.get("/calendar-years", response_model=CalendarYearsResponse)
def get_calendar_year_returns(
    scope: str = "total",
    benchmark_instrument_id: int | None = Query(default=None),
    asset_classes: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> CalendarYearsResponse:
    """One TWR figure per calendar year (spec 4.2's periods, cut the way
    people actually narrate their own finances).

    Computed from a single value/flow pass over the whole history rather
    than one request per year: the years have to chain back to the
    since-inception figure, and that identity only holds if every year is
    measured against the previous one's close — see
    `calendar_year_slices`.
    """
    try:
        scope_filter = parse_scope(scope)
    except InvalidScopeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_scope", "params": {"scope": scope}},
        ) from None
    scope_filter = dataclass_replace(
        scope_filter, asset_classes=_parsed_asset_classes(asset_classes)
    )

    end = _window_end(db)
    inception = inception_date(db, scope_filter)
    if inception is None or inception > end:
        return CalendarYearsResponse(scope=scope, method="twr", years=[])

    # From 1 January of the inception year, not from inception itself:
    # the leading days simply read as zero and `daily_returns` skips a
    # zero base, so this costs nothing and keeps every year's slice
    # aligned to real calendar boundaries.
    start = date(inception.year, 1, 1)
    values = value_series(db, scope_filter, start, end)
    flows = flow_events(db, scope_filter, start, end)

    benchmark_years: dict[int, list[tuple[date, Decimal]]] = {}
    if benchmark_instrument_id is not None:
        dates = [d for d, _ in values]
        prices = benchmark_price_series(db, benchmark_instrument_id, dates)
        shadow = shadow_value_series(dates, flows, prices, opening_value=Decimal(0))
        benchmark_years = dict(calendar_year_slices(shadow))

    years: list[CalendarYearReturnRead] = []
    for year, chunk in calendar_year_slices(values):
        year_start = max(date(year, 1, 1), inception)
        year_end = min(date(year, 12, 31), end)
        returns = daily_returns(chunk, flows)
        benchmark_chunk = benchmark_years.get(year)
        benchmark_returns = (
            daily_returns(benchmark_chunk, flows) if benchmark_chunk else []
        )
        years.append(
            CalendarYearReturnRead(
                year=year,
                start_date=year_start,
                end_date=year_end,
                partial=year_start > date(year, 1, 1) or year_end < date(year, 12, 31),
                return_pct=float(chain_link(returns)) if returns else None,
                benchmark_return_pct=(
                    float(chain_link(benchmark_returns)) if benchmark_returns else None
                ),
            )
        )
    return CalendarYearsResponse(scope=scope, method="twr", years=years)


@router.get("/by-instrument", response_model=InstrumentReturnsResponse)
def get_returns_by_instrument(
    period: str = "1Y",
    method: str = "twr",
    asset_classes: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> InstrumentReturnsResponse:
    """The same numbers `?scope=instrument:N` gives, for every instrument
    at once (spec 4.2: TWR/MWR "in total, per account or per instrument").

    A batch endpoint rather than N client requests because
    `inception_date` and `value_series` each re-scan the snapshot table,
    so a ranking built one request at a time is quadratic on the Pi. The
    equivalence with the single-scope endpoint is asserted in
    tests/test_performance_by_instrument.py — it is the property that
    makes this safe to read.
    """
    if method not in ("twr", "mwr"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_method", "params": {"method": method}},
        )
    scope_filter = ScopeFilter(asset_classes=_parsed_asset_classes(asset_classes))

    end = _window_end(db)
    inceptions = inception_dates_by_instrument(db, scope_filter)
    # Validate the period even with nothing to report, so a typo is a 400
    # on an empty database exactly as it is on a full one.
    try:
        earliest = min(inceptions.values()) if inceptions else end
        start = period_start(period, end, earliest)
    except InvalidPeriodError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_period", "params": {"period": period}},
        ) from None
    if not inceptions:
        return InstrumentReturnsResponse(
            period=period, method=method, start_date=start, end_date=end, instruments=[]
        )
    if start < earliest:
        start = earliest

    # One day earlier than the window so MWR has the pre-window opening
    # value it needs; `_series_from` drops it again for TWR. Same
    # convention as the single-scope endpoint above — see its start_value
    # note for why that value must come from the day *before* `start`.
    pre_start = start - timedelta(days=1)
    values_by_instrument = value_series_by_instrument(db, scope_filter, pre_start, end)
    flows_by_instrument = flow_events_by_instrument(db, scope_filter, start, end)
    names = {
        i.id: i
        for i in db.query(Instrument).filter(
            Instrument.id.in_(list(values_by_instrument) or [-1])
        )
    }

    rows: list[InstrumentReturnRead] = []
    for instrument_id, full_series in values_by_instrument.items():
        instrument = names.get(instrument_id)
        if instrument is None:
            continue
        flows = flows_by_instrument.get(instrument_id, [])
        window = full_series[1:]
        if not window:
            continue
        row_start = max(start, inceptions.get(instrument_id, start))

        if method == "twr":
            returns = daily_returns(window, flows)
            return_pct = float(chain_link(returns)) if returns else None
        else:
            start_value = full_series[0][1]
            end_value = window[-1][1]
            return_pct = mwr(start, start_value, flows, end, end_value)

        rows.append(
            InstrumentReturnRead(
                instrument_id=instrument_id,
                name=instrument.name,
                asset_class=instrument.asset_class.value,
                start_date=row_start,
                end_date=end,
                return_pct=return_pct,
                value_eur=window[-1][1],
            )
        )

    # Best first, name as the tiebreaker, unrankable rows last — so the
    # response has a defined order before any client sorts it.
    rows.sort(key=lambda r: (r.return_pct is None, -(r.return_pct or 0.0), r.name))
    return InstrumentReturnsResponse(
        period=period, method=method, start_date=start, end_date=end, instruments=rows
    )
