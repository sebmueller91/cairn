"""The snapshot engine (spec 3.7): for every day since the first
transaction, materializes position values, cash balances, and the three
notions of wealth from spec 4.1 — so a 10-year chart doesn't refold the
entire ledger on every request (ADR 0003). Always a cache:
`rebuild_snapshots` recreates it completely and is the ground truth. No
watermark/incremental optimization yet — that can only ever make this
*faster*, never *different*, so it's deferred until the full-table
dataset volume actually needs it.

Phase 5 extends MARKET/NOMINAL (phase 2) with ANCHORED/MODELED (house,
car — via app.valuation_service, called directly per day rather than
precomputed into a carry-forward series like MARKET prices, since a
household realistically has one house and one car, not dozens of
instruments) and AMORTIZING_LIABILITY (loan balances, via
app.loan_service). 'investable' keeps its phase-2 meaning; 'gross' adds
house/car; 'net' subtracts loan balances from 'gross' — exactly spec
4.1's three perspectives, computed once here rather than three times at
read time.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.cash_service import all_known_deposits, interpolate_cash_balance
from app.ledger import compute_positions, txn_to_event
from app.loan_service import LoanConfig, loan_balance
from app.models import (
    Account,
    AccountType,
    DailySnapshot,
    FxRate,
    Instrument,
    Loan,
    PricePoint,
    Txn,
    TransactionType,
    ValuationMode,
)
from app.valuation_service import current_instrument_value


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
    # Deposits are derived purely from each *portfolio's* own settlement
    # balance (spec 3.6: "for a portfolio, a deposit is always external
    # regardless of which account it came from") — nothing in the data
    # model records which CASH account actually funded a given one. Handing
    # the same list to every cash account's interpolation smeared a
    # withdrawal that happened in one account onto every other cash
    # account too: an account that never funded anything would show a
    # phantom rise-then-drop around the deposit's date, self-healing at
    # the next statement and so easy to miss.
    #
    # The one case this can be resolved unambiguously is a single cash
    # account — nothing else could have funded it. With more than one, we
    # deliberately withhold the correction (each account falls back to
    # plain linear interpolation between its own statements) rather than
    # guess which one it was; see the fix's report for the open gap this
    # leaves in the true funding account's mid-period shape.
    known_deposits = (
        [(d.date, d.amount_eur) for d in all_known_deposits(db)]
        if len(cash_accounts) == 1
        else []
    )
    cash_daily: dict[int, dict[date, Decimal]] = {}
    # Last interpolated day per cash account, and the balance there — see
    # the carry-forward in the snapshot loop below.
    cash_last: dict[int, tuple[date, Decimal]] = {}
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
            series = interpolate_cash_balance(
                [(s.date, s.amount_eur) for s in statements], known_deposits
            )
            cash_daily[account.id] = series
            if series:
                last_day = max(series)
                cash_last[account.id] = (last_day, series[last_day])

    loans = db.query(Loan).all()
    loan_configs: dict[int, LoanConfig] = {}
    for loan in loans:
        extra_repayments = [
            (t.date, t.amount_eur)
            for t in db.query(Txn)
            .filter(
                Txn.account_id == loan.account_id,
                Txn.type == TransactionType.EXTRA_REPAYMENT,
                Txn.voided_at.is_(None),
            )
            .all()
        ]
        loan_configs[loan.id] = LoanConfig(
            principal=loan.principal,
            annual_rate_pct=loan.rate_pct,
            start_date=loan.start_date,
            monthly_payment=loan.monthly_payment,
            extra_repayments=extra_repayments,
            payment_day=loan.payment_day,
            fixed_until=loan.fixed_until,
        )

    all_dates = list(snapshot_dates)
    for daily in cash_daily.values():
        all_dates.extend(daily.keys())
    for loan in loans:
        all_dates.append(loan.start_date)
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

        investable_value = Decimal(0)
        physical_asset_value = Decimal(0)
        for (account_id, instrument_id), pos in current_positions.items():
            if pos.quantity == 0:
                continue
            instrument = instruments.get(instrument_id)
            if instrument is None:
                continue

            if instrument.valuation_mode == ValuationMode.MARKET:
                prices = price_series.get(instrument_id)
                if not prices:
                    # No price has ever been recorded for this instrument —
                    # genuinely missing (data_quality_service's own
                    # "missing_price" check already flags this on its own,
                    # independent of what we do here), not a gap to paper
                    # over: there is nothing anywhere to value it with.
                    continue
                price = _lookup_carry_forward(prices, day, idx_cache)
                if price is None:
                    # Before this instrument's very first price point —
                    # e.g. bought a few days before the price feed/backfill
                    # caught up to it. _lookup_carry_forward already
                    # carries the latest known price forward through any
                    # *later* gap (that's its whole job); this is the one
                    # stretch it can't cover, since there is nothing
                    # earlier to carry. Reading it as zero would both
                    # understate net worth for those days and corrupt the
                    # return series with a phantom loss-then-gain the
                    # moment the first real price lands, while the BUY's
                    # own flow is already counted. Fall back to the
                    # earliest price this instrument will ever have — the
                    # same "absence of a snapshot is absence of news"
                    # principle the cash-balance carry-forward below
                    # applies, run in the only direction available before
                    # any data exists at all.
                    price = prices[0][1]
                if instrument.currency == "EUR":
                    fx = Decimal(1)
                else:
                    rates = fx_series.get(instrument.currency)
                    if not rates:
                        continue
                    fx = _lookup_carry_forward(rates, day, idx_cache)
                    if fx is None:
                        fx = rates[0][1]
                if instrument.fine_weight_g is not None:
                    # Physical metals (spec 3.2): the instrument is a
                    # physical unit, not a spot-priced share.
                    # value = fine weight (g) x spot(EUR/gram). Fine
                    # weight = quantity (pieces) x fine_weight_g (g per
                    # piece); `price` must be sourced per gram for this to
                    # be correct — the instrument's own price series is
                    # trusted as-is, whatever unit it was entered in.
                    value_eur = pos.quantity * instrument.fine_weight_g * price * fx
                else:
                    value_eur = pos.quantity * price * fx
                investable_value += value_eur
            elif instrument.valuation_mode in (ValuationMode.ANCHORED, ValuationMode.MODELED):
                value_eur = current_instrument_value(db, instrument_id, day)
                if value_eur is None:
                    continue
                physical_asset_value += value_eur
            else:
                continue

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

        for account_id, daily in cash_daily.items():
            balance = daily.get(day)
            if balance is None:
                last = cash_last.get(account_id)
                # Interpolation only spans first statement → last statement.
                # Before the first there is genuinely nothing to report;
                # after the last there is no new information, which is not
                # the same as a balance of zero. Carry the last reported
                # figure forward — the same rule prices follow above — or
                # the entire cash balance drops out of net worth on the
                # day after the last statement, silently and by thousands.
                # data_quality_service flags the balance as it ages so the
                # carried figure is never mistaken for a fresh one.
                if last is None or day < last[0]:
                    continue
                balance = last[1]
            db.add(
                DailySnapshot(
                    date=day,
                    scope_type="cash_account",
                    scope_id=str(account_id),
                    value_eur=balance,
                )
            )
            investable_value += balance

        liabilities_value = Decimal(0)
        for loan in loans:
            if day < loan.start_date:
                continue
            balance = loan_balance(loan_configs[loan.id], day)
            db.add(
                DailySnapshot(
                    date=day,
                    scope_type="loan",
                    scope_id=str(loan.id),
                    value_eur=-balance,
                )
            )
            liabilities_value += balance

        gross_value = investable_value + physical_asset_value
        net_value = gross_value - liabilities_value

        db.add(
            DailySnapshot(
                date=day, scope_type="total", scope_id="investable", value_eur=investable_value
            )
        )
        db.add(
            DailySnapshot(date=day, scope_type="total", scope_id="gross", value_eur=gross_value)
        )
        db.add(
            DailySnapshot(date=day, scope_type="total", scope_id="net", value_eur=net_value)
        )
        days_written += 1
        day += timedelta(days=1)

    db.commit()
    return days_written
