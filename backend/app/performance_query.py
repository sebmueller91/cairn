"""DB-facing orchestration for spec 4.2's return metrics: pulls the daily
value series and flow events out of the ledger/snapshot tables and hands
them to the pure functions in performance_service.py. Kept separate so the
return math itself stays testable without a database (AGENTS.md: tests
before the feature for anything that calculates).
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import DailySnapshot, FxRate, Instrument, PricePoint, Txn, TransactionType, ValuationMode
from app.performance_service import FlowEvent
from app.valuation_service import current_instrument_value

PERIODS = ("1M", "3M", "YTD", "1Y", "3Y", "5Y", "inception")


class InvalidScopeError(ValueError):
    pass


class InvalidPeriodError(ValueError):
    pass


@dataclass(frozen=True)
class ScopeFilter:
    account_id: int | None = None
    instrument_id: int | None = None


def parse_scope(scope: str) -> ScopeFilter:
    if scope == "total":
        return ScopeFilter()
    if scope.startswith("account:"):
        try:
            return ScopeFilter(account_id=int(scope.split(":", 1)[1]))
        except ValueError:
            raise InvalidScopeError(scope) from None
    if scope.startswith("instrument:"):
        try:
            return ScopeFilter(instrument_id=int(scope.split(":", 1)[1]))
        except ValueError:
            raise InvalidScopeError(scope) from None
    raise InvalidScopeError(scope)


def period_start(period: str, end: date, inception: date | None) -> date:
    if period == "1M":
        return end - timedelta(days=30)
    if period == "3M":
        return end - timedelta(days=91)
    if period == "YTD":
        return date(end.year, 1, 1)
    if period == "1Y":
        return end - timedelta(days=365)
    if period == "3Y":
        return end - timedelta(days=365 * 3)
    if period == "5Y":
        return end - timedelta(days=365 * 5)
    if period == "inception":
        return inception or end
    raise InvalidPeriodError(period)


def inception_date(db: Session, scope: ScopeFilter) -> date | None:
    """Earliest day any MARKET position existed within scope — the
    "since inception" period start."""
    market_ids = _market_instrument_ids(db)
    if not market_ids:
        return None
    rows = (
        db.query(DailySnapshot.date, DailySnapshot.scope_id)
        .filter(DailySnapshot.scope_type == "position")
        .all()
    )
    earliest: date | None = None
    for d, scope_id in rows:
        account_id_str, instrument_id_str = scope_id.split(":")
        instrument_id = int(instrument_id_str)
        if instrument_id not in market_ids:
            continue
        if scope.account_id is not None and int(account_id_str) != scope.account_id:
            continue
        if scope.instrument_id is not None and instrument_id != scope.instrument_id:
            continue
        if earliest is None or d < earliest:
            earliest = d
    return earliest


def benchmark_price_series(
    db: Session, instrument_id: int, dates: list[date]
) -> dict[date, Decimal]:
    """EUR-converted, carry-forward-resolved price for a MARKET instrument
    on each of `dates` (assumed sorted, dense) — the input the benchmark
    overlay's shadow portfolio needs. A date before the instrument's
    first known price is simply absent (nothing to carry forward yet)."""
    if not dates:
        return {}
    instrument = db.get(Instrument, instrument_id)
    if instrument is None or instrument.valuation_mode != ValuationMode.MARKET:
        return {}

    price_rows = (
        db.query(PricePoint)
        .filter(PricePoint.instrument_id == instrument_id, PricePoint.date <= dates[-1])
        .order_by(PricePoint.date)
        .all()
    )
    if instrument.currency == "EUR":
        fx_rows: list[tuple[date, Decimal]] = []
    else:
        fx_rows = [
            (r.date, r.eur_rate)
            for r in db.query(FxRate)
            .filter(FxRate.currency == instrument.currency, FxRate.date <= dates[-1])
            .order_by(FxRate.date)
            .all()
        ]

    result: dict[date, Decimal] = {}
    price_idx, price_val = -1, None
    fx_idx, fx_val = -1, (Decimal(1) if instrument.currency == "EUR" else None)
    for d in dates:
        while price_idx + 1 < len(price_rows) and price_rows[price_idx + 1].date <= d:
            price_idx += 1
            price_val = price_rows[price_idx].close
        while fx_rows and fx_idx + 1 < len(fx_rows) and fx_rows[fx_idx + 1][0] <= d:
            fx_idx += 1
            fx_val = fx_rows[fx_idx][1]
        if price_val is not None and fx_val is not None:
            result[d] = price_val * fx_val
    return result


def _market_instrument_ids(db: Session) -> set[int]:
    return {
        row[0]
        for row in db.query(Instrument.id).filter(
            Instrument.valuation_mode == ValuationMode.MARKET
        )
    }


def value_series(
    db: Session, scope: ScopeFilter, start: date, end: date
) -> list[tuple[date, Decimal]]:
    """Daily sum of MARKET-instrument position values within scope, dense
    across [start, end]. A day with no matching `daily_snapshot` rows
    reads as 0 — either genuinely nothing invested yet/fully liquidated,
    or (same convention the dashboard's own net-worth total already uses)
    a missing price that day, silently omitted rather than gap-filled.
    Task 72's data-quality panel is where stale/missing prices actually
    get surfaced; this function doesn't try to detect that."""
    if start > end:
        return []
    market_ids = _market_instrument_ids(db)
    rows = (
        db.query(DailySnapshot)
        .filter(
            DailySnapshot.scope_type == "position",
            DailySnapshot.date >= start,
            DailySnapshot.date <= end,
        )
        .all()
    )
    by_date: dict[date, Decimal] = {}
    for row in rows:
        account_id_str, instrument_id_str = row.scope_id.split(":")
        instrument_id = int(instrument_id_str)
        if instrument_id not in market_ids:
            continue
        if scope.account_id is not None and int(account_id_str) != scope.account_id:
            continue
        if scope.instrument_id is not None and instrument_id != scope.instrument_id:
            continue
        by_date[row.date] = by_date.get(row.date, Decimal(0)) + row.value_eur

    series: list[tuple[date, Decimal]] = []
    d = start
    while d <= end:
        series.append((d, by_date.get(d, Decimal(0))))
        d += timedelta(days=1)
    return series


def flow_events(
    db: Session, scope: ScopeFilter, start: date, end: date
) -> list[FlowEvent]:
    """BUY/SELL are flows at every scope (money entering/leaving the
    MARKET-position universe from untracked settlement cash). TRANSFER
    only matters relative to a single account or instrument scope — at
    scope=total it nets to zero (quantity just moves between two of the
    household's own buckets), so it's not even queried for there."""
    if start > end:
        return []
    market_ids = _market_instrument_ids(db)
    types = [TransactionType.BUY, TransactionType.SELL]
    if scope.account_id is not None:
        types.append(TransactionType.TRANSFER)

    query = db.query(Txn).filter(
        Txn.voided_at.is_(None),
        Txn.date >= start,
        Txn.date <= end,
        Txn.type.in_(types),
    )
    if scope.account_id is not None:
        query = query.filter(
            (Txn.account_id == scope.account_id)
            | (Txn.counter_account_id == scope.account_id)
        )
    if scope.instrument_id is not None:
        query = query.filter(Txn.instrument_id == scope.instrument_id)

    flows: list[FlowEvent] = []
    for t in query.all():
        if t.instrument_id not in market_ids:
            continue
        if t.type == TransactionType.BUY:
            flows.append(FlowEvent(t.date, t.amount_eur))
        elif t.type == TransactionType.SELL:
            flows.append(FlowEvent(t.date, -t.amount_eur))
        elif t.type == TransactionType.TRANSFER:
            unit_price = current_instrument_value(db, t.instrument_id, t.date)
            if unit_price is None or t.quantity is None:
                continue
            market_value = unit_price * t.quantity
            if t.account_id == scope.account_id:
                flows.append(FlowEvent(t.date, -market_value))
            elif t.counter_account_id == scope.account_id:
                flows.append(FlowEvent(t.date, market_value))
    return flows
