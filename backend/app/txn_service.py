"""Validation and amount_eur derivation for writing transactions.

Kept separate from the router so it can be unit tested without going
through HTTP, and separate from app.ledger (which only ever sees
already-converted EUR amounts and knows nothing about accounts/instruments
existing in the database).
"""

import hashlib
import json
from datetime import date as date_type
from decimal import Decimal

from sqlalchemy.orm import Session

from app.ledger import InsufficientHoldingError, TxnEvent, compute_positions, txn_to_event
from app.models import (
    Account,
    AccountType,
    FxRate,
    Instrument,
    PriceMode,
    PricePoint,
    Txn,
    TransactionType,
)
from app.schemas import UNSUPPORTED_TXN_TYPES, TransactionCreate

_AMOUNT_ONLY_TYPES = {
    TransactionType.DIVIDEND,
    TransactionType.INTEREST,
    TransactionType.FEE,
    TransactionType.TAX,
    TransactionType.DEPOSIT,
    TransactionType.WITHDRAWAL,
    TransactionType.BALANCE_STATEMENT,
    # Record-keeping / cash-flow tracking only — the loan balance itself
    # comes from loan_service's amortization model, not from summing
    # these. interest_part/principal_part (spec 2.3) aren't stored
    # separately: both are always derivable from the loan's own rate and
    # the balance just before this payment, so storing them too would be
    # a second, driftable copy of the same number.
    TransactionType.LOAN_PAYMENT,
    # EXTRA_REPAYMENT is the one type that actually feeds back into the
    # model — loan_service reads these directly off the ledger by type
    # and account, not from a separate config list.
    TransactionType.EXTRA_REPAYMENT,
}

_LOAN_ONLY_TYPES = {TransactionType.LOAN_PAYMENT, TransactionType.EXTRA_REPAYMENT}


class TxnValidationError(Exception):
    def __init__(self, code: str, params: dict | None = None):
        self.code = code
        self.params = params or {}
        super().__init__(code)


def _require(payload: TransactionCreate, *fields: str) -> None:
    for field in fields:
        if getattr(payload, field) is None:
            raise TxnValidationError("missing_field", {"field": field})


def resolve_fx_rate(db: Session, payload: TransactionCreate) -> Decimal:
    if payload.currency == "EUR":
        return Decimal(1)
    if payload.fx_rate is not None:
        return payload.fx_rate
    row = db.get(FxRate, (payload.currency, payload.date))
    if row is None:
        raise TxnValidationError(
            "fx_rate_required",
            {"currency": payload.currency, "date": str(payload.date)},
        )
    return row.eur_rate


def resolve_price(db: Session, payload: TransactionCreate) -> Decimal | None:
    """BUY/SELL only. An explicit price wins; otherwise, with
    price_mode='auto', falls back to the closest price_point at or
    before the txn date — spec 2.5: a purchase with an unknown price is
    still bookable, and becomes exact once a document supplies it later
    (just re-PATCH the price then; auto only ever fills a gap, it
    doesn't paper over one permanently)."""
    if payload.type not in (TransactionType.BUY, TransactionType.SELL):
        return None
    if payload.price is not None:
        return payload.price
    if payload.price_mode != PriceMode.AUTO or payload.instrument_id is None:
        return None
    row = (
        db.query(PricePoint)
        .filter(
            PricePoint.instrument_id == payload.instrument_id,
            PricePoint.date <= payload.date,
        )
        .order_by(PricePoint.date.desc())
        .first()
    )
    if row is None:
        raise TxnValidationError(
            "no_price_available",
            {"instrument_id": payload.instrument_id, "date": str(payload.date)},
        )
    return row.close


def compute_amount_eur(
    payload: TransactionCreate, fx_rate: Decimal, resolved_price: Decimal | None = None
) -> Decimal:
    t = payload.type
    if t == TransactionType.BUY:
        _require(payload, "quantity")
        price = resolved_price if resolved_price is not None else payload.price
        if price is None:
            raise TxnValidationError("missing_field", {"field": "price"})
        gross = payload.quantity * price * fx_rate
        return gross + payload.fees * fx_rate
    if t == TransactionType.SELL:
        _require(payload, "quantity")
        price = resolved_price if resolved_price is not None else payload.price
        if price is None:
            raise TxnValidationError("missing_field", {"field": "price"})
        gross = payload.quantity * price * fx_rate
        return gross - payload.fees * fx_rate - payload.tax * fx_rate
    if t == TransactionType.OPENING_BALANCE:
        _require(payload, "quantity", "amount")
        return payload.amount * fx_rate
    if t in _AMOUNT_ONLY_TYPES:
        _require(payload, "amount")
        return payload.amount * fx_rate
    if t == TransactionType.TRANSFER:
        _require(payload, "quantity", "counter_account_id")
        return -(payload.fees * fx_rate) if payload.fees else Decimal(0)
    if t == TransactionType.SPLIT:
        _require(payload, "instrument_id", "split_ratio")
        return Decimal(0)
    raise TxnValidationError("unsupported_transaction_type", {"type": t.value})


def validate_references(db: Session, payload: TransactionCreate) -> None:
    if payload.type in UNSUPPORTED_TXN_TYPES:
        raise TxnValidationError(
            "unsupported_transaction_type",
            {"type": payload.type.value, "reason": "requires a phase-5 table"},
        )
    if payload.date > date_type.today():
        raise TxnValidationError("future_date", {"date": str(payload.date)})

    account = db.get(Account, payload.account_id)
    if account is None:
        raise TxnValidationError("unknown_account", {"account_id": payload.account_id})
    if account.opened_at and payload.date < account.opened_at:
        raise TxnValidationError(
            "date_before_account_opened",
            {"date": str(payload.date), "opened_at": str(account.opened_at)},
        )

    if payload.counter_account_id is not None:
        counter = db.get(Account, payload.counter_account_id)
        if counter is None:
            raise TxnValidationError(
                "unknown_account", {"account_id": payload.counter_account_id}
            )

    if payload.instrument_id is not None:
        instrument = db.get(Instrument, payload.instrument_id)
        if instrument is None:
            raise TxnValidationError(
                "unknown_instrument", {"instrument_id": payload.instrument_id}
            )

    if payload.type in _LOAN_ONLY_TYPES and account.type != AccountType.LOAN:
        raise TxnValidationError(
            "not_a_loan_account",
            {"account_id": payload.account_id, "type": payload.type.value},
        )


def check_holdings(db: Session, payload: TransactionCreate) -> None:
    """Replays existing history plus this candidate transaction to catch
    an oversell before it's written — cheap at this data volume, and the
    only way to be sure, since a SELL can be invalidated by any prior
    transaction for the same (account, instrument)."""
    if payload.type not in (TransactionType.SELL, TransactionType.TRANSFER):
        return

    existing = (
        db.query(Txn)
        .filter(
            Txn.instrument_id == payload.instrument_id,
            Txn.voided_at.is_(None),
        )
        .all()
    )
    events = [txn_to_event(t) for t in existing]
    max_id = max((t.id for t in existing), default=0)
    events.append(
        TxnEvent(
            order=max_id + 1,
            type=payload.type,
            date=payload.date,
            account_id=payload.account_id,
            instrument_id=payload.instrument_id,
            counter_account_id=payload.counter_account_id,
            quantity=payload.quantity,
            amount_eur=Decimal(0),
        )
    )
    try:
        compute_positions(events)
    except InsufficientHoldingError as e:
        raise TxnValidationError(
            "sell_exceeds_holding",
            {
                "account_id": e.account_id,
                "instrument_id": e.instrument_id,
                "requested": str(e.requested),
                "available": str(e.available),
            },
        )


def payload_hash(payload: TransactionCreate) -> str:
    """Used to distinguish an identical resend (idempotent no-op) from a
    genuinely different payload reusing the same external_id (409)."""
    normalized = json.dumps(
        payload.model_dump(mode="json", exclude={"source"}), sort_keys=True
    )
    return hashlib.sha256(normalized.encode()).hexdigest()


def build_txn(
    payload: TransactionCreate,
    import_batch_id: int,
    amount_eur: Decimal,
    fx_rate_used: Decimal,
    resolved_price: Decimal | None = None,
) -> Txn:
    return Txn(
        external_id=payload.external_id,
        payload_hash=payload_hash(payload),
        import_batch_id=import_batch_id,
        date=payload.date,
        date_precision=payload.date_precision,
        type=payload.type,
        account_id=payload.account_id,
        instrument_id=payload.instrument_id,
        counter_account_id=payload.counter_account_id,
        quantity=payload.quantity,
        # Stored even when auto-resolved, so the position math and any
        # display of this row has a real number — price_mode is what
        # still marks it as not manually verified, not a null price.
        price=resolved_price if resolved_price is not None else payload.price,
        price_mode=payload.price_mode,
        currency=payload.currency,
        fx_rate=fx_rate_used if payload.currency != "EUR" else None,
        split_ratio=payload.split_ratio,
        fees=payload.fees,
        tax=payload.tax,
        amount_eur=amount_eur,
        provisional=payload.provisional,
        note=payload.note,
        source=payload.source,
    )
