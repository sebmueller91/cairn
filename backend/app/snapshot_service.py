"""The snapshot engine (spec 3.7): for every day since the first
transaction, materializes position values, cash balances, and a total —
so a 10-year chart doesn't refold the entire ledger on every request
(ADR 0003). Always a cache: `rebuild_snapshots` recreates it completely
and is the ground truth. No watermark/incremental optimization yet — that
can only ever make this *faster*, never *different*, so it's deferred
until the full-table dataset volume actually needs it.

Scope covered in phase 2: MARKET-valued positions and NOMINAL cash
accounts only. ANCHORED/MODELED/AMORTIZING_LIABILITY (house, car, loan)
arrive in phase 5 and extend this same table, not a new one.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.cash_service import all_known_deposits, interpolate_cash_balance
from app.ledger import compute_positions, txn_to_event
from app.models import (
    Account,
    AccountType,
    DailySnapshot,
    FxRate,
    Instrument,
    PricePoint,
    Txn,
)


def _quantity_snapshots_by_date(events: list) -> dict[date, dict]:
    """Position state as of end-of-day for every date a transaction
    occurred — sparse, carried forward between these dates during the
    daily valuation walk. Recomputing via compute_positions once per
    distinct transaction date (not once per calendar day) keeps this to
    O(distinct dates x n log n) rather than O(calendar days x n log n)."""
    distinct_dates = sorted({e.date for e in events})
    snapshots = {}
    for d in distinct_dates:
        subset = [e for e in events if e.date <= d]
        snapshots[d] = compute_positions(subset)
    return snapshots


def _carry_forward_series(rows: list[tuple[date, Decimal]]) -> list[tuple[date, Decimal]]:
    return sorted(rows, key=lambda r: r[0])


def _lookup_carry_forward(series: list[tuple[date, Decimal]], as_of: date, idx_cache: dict) -> Decimal | None:
    """Latest value at or before `as_of`. `series` must be date-sorted;
    `idx_cache` lets repeated calls with increasing `as_of` (the normal
    daily-walk access pattern) advance a pointer instead of re-scanning."""
    idx = idx_cache.get(id(series), -1)
    value = None if idx < 0 else series[idx][1]
    n = len(series)
    while idx + 1 < n and series[idx + 1][0] <= as_of:
        idx += 1
        value = series[idx][1]
    idx_cache[id(series)] = idx
    return value


def rebuild_snapshots(db: Session) -> int:
    """Full rebuild. Wipes and recreates daily_snapshot entirely — always
    correct, regardless of what state the table was in before. Returns
    the number of days snapshotted."""
    all_txns = (
        db.query(Txn)
        .filter(Txn.voided_at.is_(None), Txn.instrument_id.isnot(None))
        .all()
    )
    events = [txn_to_event(t) for t in all_txns]

    instruments = {i.id: i for i in db.query(Instrument).all()}
    price_series: dict[int, list[tuple[date, Decimal]]] = {}
    for p in db.query(PricePoint).all():
        price_series.setdefault(p.instrument_id, []).append((p.date, p.close))
    for k in price_series:
        price_series[k] = _carry_forward_series(price_series[k])

    fx_series: dict[str, list[tuple[date, Decimal]]] = {}
    for f in db.query(FxRate).all():
        fx_series.setdefault(f.currency, []).append((f.date, f.eur_rate))
    for k in fx_series:
        fx_series[k] = _carry_forward_series(fx_series[k])

    qty_snapshots = _quantity_snapshots_by_date(events)
    snapshot_dates = sorted(qty_snapshots)

    cash_accounts = (
        db.query(Account).filter(Account.type == AccountType.CASH).all()
    )
    known_deposits = [(d.date, d.amount_eur) for d in all_known_deposits(db)]
    cash_daily: dict[int, dict[date, Decimal]] = {}
    for account in cash_accounts:
        statements = (
            db.query(Txn)
            .filter(
                Txn.account_id == account.id,
                Txn.type == "BALANCE_STATEMENT",
                Txn.voided_at.is_(None),
            )
            .order_by(Txn.date)
            .all()
        )
        if statements:
            cash_daily[account.id] = interpolate_cash_balance(
                [(s.date, s.amount_eur) for s in statements], known_deposits
            )

    all_dates = list(snapshot_dates)
    for daily in cash_daily.values():
        all_dates.extend(daily.keys())
    if not all_dates:
        db.query(DailySnapshot).delete()
        db.commit()
        return 0

    first_date = min(all_dates)
    last_date = date.today()

    db.query(DailySnapshot).delete()

    idx_cache: dict = {}
    current_positions: dict = {}
    snap_idx = 0
    days_written = 0
    day = first_date
    while day <= last_date:
        while snap_idx < len(snapshot_dates) and snapshot_dates[snap_idx] <= day:
            current_positions = qty_snapshots[snapshot_dates[snap_idx]]
            snap_idx += 1

        total_value = Decimal(0)
        for (account_id, instrument_id), pos in current_positions.items():
            if pos.quantity == 0:
                continue
            instrument = instruments.get(instrument_id)
            if instrument is None or instrument.valuation_mode != "MARKET":
                continue
            prices = price_series.get(instrument_id)
            if not prices:
                continue
            price = _lookup_carry_forward(prices, day, idx_cache)
            if price is None:
                continue
            if instrument.currency == "EUR":
                fx = Decimal(1)
            else:
                rates = fx_series.get(instrument.currency)
                fx = _lookup_carry_forward(rates, day, idx_cache) if rates else None
                if fx is None:
                    continue
            value_eur = pos.quantity * price * fx
            db.add(
                DailySnapshot(
                    date=day,
                    scope_type="position",
                    scope_id=f"{account_id}:{instrument_id}",
                    quantity=pos.quantity,
                    value_eur=value_eur,
                    cost_basis_eur=pos.cost_basis_eur,
                )
            )
            total_value += value_eur

        for account_id, daily in cash_daily.items():
            balance = daily.get(day)
            if balance is None:
                continue
            db.add(
                DailySnapshot(
                    date=day,
                    scope_type="cash_account",
                    scope_id=str(account_id),
                    value_eur=balance,
                )
            )
            total_value += balance

        db.add(
            DailySnapshot(
                date=day, scope_type="total", scope_id="investable", value_eur=total_value
            )
        )
        days_written += 1
        day += timedelta(days=1)

    db.commit()
    return days_written
