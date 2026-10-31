"""Standing rules for savings plans and loan instalments (ADR 0016), and
a manual trigger for the nightly job that books them.

A rule's own writes are configuration, audited like loans.py's. The
transactions it produces go through app/recurring_service.py, which
uses the same validation as POST /api/transactions.
"""

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import audit
from app.auth import get_scope, require_write_scope
from app.database import get_db
from app.models import (
    Account,
    AccountType,
    Instrument,
    Loan,
    RecurringBooking,
    TransactionType,
    TxnSource,
)
from app.recurring_service import SUPPORTED_TYPES, book_due
from app.schemas import (
    RecurringBookingCreate,
    RecurringBookingRead,
    RecurringBookingUpdate,
    RecurringRunFailure,
    RecurringRunResponse,
    TransactionRead,
)

router = APIRouter(prefix="/api/recurring-bookings", tags=["recurring-bookings"])


def _reject(code: str, params: dict, status_code: int = status.HTTP_422_UNPROCESSABLE_ENTITY):
    raise HTTPException(status_code=status_code, detail={"code": code, "params": params})


def _validate(db: Session, rule: RecurringBooking) -> None:
    if rule.type not in SUPPORTED_TYPES:
        _reject("unsupported_recurring_type", {"type": rule.type.value})
    if rule.day_of_month == 0:
        _reject("invalid_day_of_month", {"day_of_month": 0})
    account = db.get(Account, rule.account_id)
    if account is None:
        _reject("account_not_found", {"id": rule.account_id}, status.HTTP_404_NOT_FOUND)
    if rule.end_date is not None and rule.end_date < rule.start_date:
        _reject(
            "end_before_start",
            {"start_date": str(rule.start_date), "end_date": str(rule.end_date)},
        )

    if rule.type == TransactionType.LOAN_PAYMENT:
        if account.type != AccountType.LOAN:
            _reject("not_a_loan_account", {"account_id": rule.account_id})
        if rule.instrument_id is not None:
            _reject("unexpected_field", {"field": "instrument_id"})
        if rule.amount_eur is None and (
            db.query(Loan).filter(Loan.account_id == rule.account_id).first() is None
        ):
            _reject("loan_not_found", {"account_id": rule.account_id})
        return

    if account.type == AccountType.LOAN:
        _reject("loan_account_not_allowed", {"account_id": rule.account_id})
    if rule.instrument_id is None:
        _reject("missing_field", {"field": "instrument_id"})
    if db.get(Instrument, rule.instrument_id) is None:
        _reject("unknown_instrument", {"instrument_id": rule.instrument_id})
    if rule.amount_eur is None:
        _reject("missing_field", {"field": "amount_eur"})
    if rule.fees >= rule.amount_eur:
        _reject(
            "fees_exceed_amount",
            {"fees": str(rule.fees), "amount_eur": str(rule.amount_eur)},
        )


@router.get("", response_model=list[RecurringBookingRead])
def list_recurring_bookings(
    db: Session = Depends(get_db), _scope=Depends(get_scope)
) -> list[RecurringBooking]:
    return db.query(RecurringBooking).order_by(RecurringBooking.id).all()


@router.post("", response_model=RecurringBookingRead, status_code=status.HTTP_201_CREATED)
def create_recurring_booking(
    body: RecurringBookingCreate,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> RecurringBooking:
    if db.query(RecurringBooking).filter(RecurringBooking.name == body.name).first():
        _reject("name_conflict", {"name": body.name}, status.HTTP_409_CONFLICT)
    rule = RecurringBooking(**body.model_dump())
    _validate(db, rule)
    db.add(rule)
    db.flush()  # assigns rule.id, needed for the audit record
    # No source field distinguishes agent from manual UI use here — same
    # convention as loans.py: every write is logged as TxnSource.AGENT.
    audit.record(
        db,
        actor=TxnSource.AGENT,
        action="create",
        entity="recurring_booking",
        entity_id=rule.id,
        payload_hash="n/a",
    )
    db.commit()
    db.refresh(rule)
    return rule


@router.patch("/{rule_id}", response_model=RecurringBookingRead)
def update_recurring_booking(
    rule_id: int,
    body: RecurringBookingUpdate,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> RecurringBooking:
    """Changes apply to occurrences not yet booked; bookings already
    written are ordinary transactions and are corrected as such."""
    rule = db.get(RecurringBooking, rule_id)
    if rule is None:
        _reject("recurring_booking_not_found", {"id": rule_id}, status.HTTP_404_NOT_FOUND)
    changes = body.model_dump(exclude_unset=True)
    diff = {}
    for name, value in changes.items():
        before = getattr(rule, name)
        if before != value:
            diff[name] = {"before": str(before), "after": str(value)}
        setattr(rule, name, value)
    _validate(db, rule)
    audit.record(
        db,
        actor=TxnSource.AGENT,
        action="update",
        entity="recurring_booking",
        entity_id=rule.id,
        payload_hash="n/a",
        diff=diff,
    )
    db.commit()
    db.refresh(rule)
    return rule


@router.post("/run", response_model=RecurringRunResponse)
def run_recurring_bookings(
    dry_run: bool = False,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> RecurringRunResponse:
    """What the nightly job does, on demand. With dry_run the bookings are
    computed and returned, then rolled back."""
    result = book_due(db)
    response = RecurringRunResponse(
        dry_run=dry_run,
        import_batch_id=None if dry_run else result.import_batch_id,
        booked=[TransactionRead.model_validate(t) for t in result.booked],
        failures=[RecurringRunFailure(**asdict(f)) for f in result.failures],
    )
    if dry_run:
        db.rollback()
    else:
        db.commit()
    return response
