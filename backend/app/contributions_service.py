"""Contributions over a window (spec 4.3, Overview's 12-month card).

Deliberately *not* attribution_service. That one explains a change in
wealth into buckets which must sum exactly to the observed delta, and
therefore needs a residual. This answers a simpler, more concrete
question — "what did I actually put in, and what did I pay off" — so it
reads transactions directly, and the three numbers it returns are not
required to reconcile with each other: money invested, principal repaid
and net-worth change are three independent facts about the same period.

Net of sales on purpose. Selling an ETF to buy another one is not fresh
money, and a 12-month figure that counted only purchases would read as
new savings when nothing was saved.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import DailySnapshot, Instrument, TransactionType, Txn


@dataclass
class Contributions:
    start_date: date
    end_date: date
    # Asset class -> net amount invested (BUY minus SELL) over the window.
    # Only classes with a non-zero figure appear.
    by_asset_class: dict[str, Decimal] = field(default_factory=dict)
    total_invested: Decimal = Decimal(0)
    # Positive when loan principal went down over the window. Drawing a new
    # loan legitimately makes this negative.
    debt_repaid: Decimal = Decimal(0)
    net_worth_change: Decimal = Decimal(0)


def _total_on(db: Session, scope_type: str, scope_id: str | None, d: date) -> Decimal:
    """Snapshot value for a scope *as of* a date — the latest snapshot on or
    before `d`, summed when scope_id is None (the `loan` scope has one row
    per loan).

    On or before, not exactly on. The snapshot job runs once in the evening,
    so for most of the day there is no row for today yet — and an exact
    match would then read as zero and report the entire outstanding loan as
    "repaid this year" and the whole opening net worth as a loss. Absence of
    a snapshot is absence of news, the same rule prices and cash balances
    follow. Genuinely nothing on or before the date (a window that starts
    before the ledger does) still reads as zero, which is correct."""
    latest = (
        db.query(func.max(DailySnapshot.date))
        .filter(DailySnapshot.scope_type == scope_type, DailySnapshot.date <= d)
    )
    if scope_id is not None:
        latest = latest.filter(DailySnapshot.scope_id == scope_id)
    as_of = latest.scalar()
    if as_of is None:
        return Decimal(0)

    q = db.query(func.sum(DailySnapshot.value_eur)).filter(
        DailySnapshot.scope_type == scope_type, DailySnapshot.date == as_of
    )
    if scope_id is not None:
        q = q.filter(DailySnapshot.scope_id == scope_id)
    return Decimal(str(q.scalar() or 0))


def compute_contributions(db: Session, start: date, end: date) -> Contributions:
    result = Contributions(start_date=start, end_date=end)

    rows = (
        db.query(Instrument.asset_class, Txn.type, func.sum(Txn.amount_eur))
        .join(Txn, Txn.instrument_id == Instrument.id)
        .filter(
            Txn.voided_at.is_(None),
            Txn.date > start,
            Txn.date <= end,
            Txn.type.in_([TransactionType.BUY, TransactionType.SELL]),
        )
        .group_by(Instrument.asset_class, Txn.type)
        .all()
    )
    totals: dict[str, Decimal] = {}
    for asset_class, txn_type, amount in rows:
        sign = 1 if txn_type == TransactionType.BUY else -1
        key = asset_class.value if hasattr(asset_class, "value") else str(asset_class)
        totals[key] = totals.get(key, Decimal(0)) + sign * Decimal(str(amount or 0))

    result.by_asset_class = {k: v for k, v in totals.items() if v != 0}
    result.total_invested = sum(result.by_asset_class.values(), Decimal(0))

    # Loan rows are stored negative, so the later (smaller) debt minus the
    # earlier one is the amount repaid.
    result.debt_repaid = _total_on(db, "loan", None, end) - _total_on(db, "loan", None, start)
    result.net_worth_change = _total_on(db, "total", "net", end) - _total_on(
        db, "total", "net", start
    )
    return result
