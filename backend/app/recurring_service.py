"""Turns standing rules (RecurringBooking: savings plans, loan
instalments) into provisional transactions — ADR 0016.

Each rule is due once a month on its `day_of_month` (clamped to the
month's last day; negative counts back from the end, -2 = second last
day). Unless the rule turns `shift_to_business_day` off, the booking is
dated on the next German business day on or after that
(app/business_days.py). Either way it is booked only once that date has
arrived. What comes out is an ordinary txn, written through the same
validation as POST /api/transactions:

- BUY: `price_mode=auto` (the instrument's own close on that date, or the
  latest one before it), quantity = (amount − fees) / price, cut — never
  rounded up — to the rule's `quantity_decimals`.
- LOAN_PAYMENT: the rule's amount, or the loan's own monthly_payment.
  Record-keeping only: the loan balance still comes from loan_service's
  amortisation schedule, which already assumes every instalment is paid.

Every booking is `provisional=True` — an estimate until the statement
confirms it. Confirming means patching the real quantity/price/fees and
clearing `provisional`; nothing here ever touches a booking again once
written.

Catches up: a run books every occurrence that fell due since the rule's
`booked_through`, so a night the container was down is not lost. A
failing occurrence (typically `no_price_available`) stops that rule for
this run without advancing `booked_through`, and the next run retries it.
"""

import calendar
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app import audit
from app.business_days import next_business_day
from app.models import (
    ImportBatch,
    Loan,
    PriceMode,
    RecurringBooking,
    TransactionType,
    Txn,
    TxnSource,
)
from app.schemas import TransactionCreate
from app.txn_service import (
    TxnValidationError,
    build_txn,
    compute_amount_eur,
    resolve_fx_rate,
    resolve_price,
    validate_references,
)

logger = logging.getLogger(__name__)

BERLIN = ZoneInfo("Europe/Berlin")

SUPPORTED_TYPES = {TransactionType.BUY, TransactionType.LOAN_PAYMENT}


@dataclass
class Failure:
    rule_id: int
    due: date
    code: str
    params: dict


@dataclass
class RunResult:
    booked: list[Txn] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)
    import_batch_id: int | None = None


def berlin_today() -> date:
    return datetime.now(BERLIN).date()


def nominal_due_date(day_of_month: int, year: int, month: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    if day_of_month < 0:
        return date(year, month, last_day + 1 + day_of_month)
    return date(year, month, min(day_of_month, last_day))


def execution_date(rule: RecurringBooking, due: date) -> date:
    return next_business_day(due) if rule.shift_to_business_day else due


def due_dates(rule: RecurringBooking, today: date) -> list[date]:
    """Nominal due dates not yet handled whose business-day execution
    date is on or before `today`, oldest first."""
    after = rule.booked_through or (rule.start_date - timedelta(days=1))
    year, month = rule.start_date.year, rule.start_date.month
    result = []
    while (year, month) <= (today.year, today.month):
        due = nominal_due_date(rule.day_of_month, year, month)
        if rule.end_date is not None and due > rule.end_date:
            break
        if due >= rule.start_date and due > after and execution_date(rule, due) <= today:
            result.append(due)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def external_id_for(rule: RecurringBooking, due: date) -> str:
    # Keyed on the nominal month, not the execution date, so a later
    # change to the holiday calendar can never re-key a month.
    return f"recurring-{rule.id}-{due:%Y-%m}"


def build_payload(db: Session, rule: RecurringBooking, due: date) -> TransactionCreate:
    common = dict(
        external_id=external_id_for(rule, due),
        date=execution_date(rule, due),
        account_id=rule.account_id,
        currency="EUR",
        provisional=True,
        note=(
            f"Recurring booking '{rule.name}', due {due.isoformat()}. "
            "Estimate until the statement confirms it."
        ),
        source=TxnSource.IMPORT,
    )

    if rule.type == TransactionType.LOAN_PAYMENT:
        amount = rule.amount_eur
        if amount is None:
            loan = db.query(Loan).filter(Loan.account_id == rule.account_id).first()
            if loan is None:
                raise TxnValidationError("loan_not_found", {"account_id": rule.account_id})
            amount = loan.monthly_payment
        return TransactionCreate(type=TransactionType.LOAN_PAYMENT, amount=amount, **common)

    base = TransactionCreate(
        type=TransactionType.BUY,
        instrument_id=rule.instrument_id,
        price_mode=PriceMode.AUTO,
        fees=rule.fees,
        **common,
    )
    price = resolve_price(db, base)
    step = Decimal(1).scaleb(-rule.quantity_decimals)
    quantity = ((rule.amount_eur - rule.fees) / price).quantize(step, rounding=ROUND_DOWN)
    if quantity <= 0:
        raise TxnValidationError(
            "invalid_quantity", {"quantity": str(quantity), "type": base.type.value}
        )
    return base.model_copy(update={"quantity": quantity})


def book_due(db: Session, today: date | None = None) -> RunResult:
    """Books every due occurrence of every active rule. Flushes but does
    not commit — the caller owns the transaction (the job commits, a dry
    run rolls back)."""
    today = today or berlin_today()
    result = RunResult()
    batch: ImportBatch | None = None

    rules = (
        db.query(RecurringBooking)
        .filter(RecurringBooking.active.is_(True))
        .order_by(RecurringBooking.id)
        .all()
    )
    for rule in rules:
        for due in due_dates(rule, today):
            external_id = external_id_for(rule, due)
            if db.query(Txn.id).filter(Txn.external_id == external_id).first():
                rule.booked_through = due
                continue
            try:
                payload = build_payload(db, rule, due)
                validate_references(db, payload)
                fx_rate = resolve_fx_rate(db, payload)
                price = resolve_price(db, payload)
                amount_eur = compute_amount_eur(payload, fx_rate, price)
            except TxnValidationError as e:
                result.failures.append(Failure(rule.id, due, e.code, e.params))
                logger.warning(
                    "recurring booking %r due %s not booked: %s %s",
                    rule.name, due, e.code, e.params,
                )
                break

            if batch is None:
                batch = ImportBatch(label=f"recurring bookings {today}", source=TxnSource.IMPORT)
                db.add(batch)
                db.flush()
                result.import_batch_id = batch.id
            txn = build_txn(payload, batch.id, amount_eur, fx_rate, price)
            db.add(txn)
            db.flush()
            # Read back what was stored: Money rounds to cents at the DB
            # boundary, and callers (the run endpoint's response) should see
            # the stored amount, not the unrounded product.
            db.refresh(txn)
            audit.record(
                db,
                actor=TxnSource.IMPORT,
                action="create",
                entity="txn",
                entity_id=txn.id,
                payload_hash=txn.payload_hash,
            )
            rule.booked_through = due
            result.booked.append(txn)
    db.flush()
    return result
