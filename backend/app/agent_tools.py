"""The in-app agent's tools (ADR 0017): what it can see, and the one way
it can change anything — proposing a set of ledger changes that a person
then applies or rejects.

Read tools call the same functions as the read endpoints. Proposed
changes go through txn_service's create/patch/delete — the exact code
behind POST/PATCH/DELETE /api/transactions — once as a dry run when
proposed (rolled back), and again for real when a person applies them.
Nothing here can touch accounts, instruments, loans, rules or settings.
"""

import json
import uuid
from datetime import date

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    Account,
    ImportBatch,
    Instrument,
    RecurringBooking,
    Txn,
    TxnSource,
)
from app.routers.positions import get_positions
from app.schemas import (
    AgentChanges,
    TransactionCreate,
    TransactionRead,
    TransactionUpdate,
)
from app.txn_service import TxnValidationError, create_txn, delete_txn, patch_txn

_DECIMAL = {"type": "string", "description": "Decimal with a dot, e.g. \"1234.56\""}
_DATE = {"type": "string", "description": "YYYY-MM-DD"}
_TXN_TYPES = [
    "BUY", "SELL", "DIVIDEND", "INTEREST", "FEE", "TAX", "DEPOSIT", "WITHDRAWAL",
    "TRANSFER", "SPLIT", "OPENING_BALANCE", "BALANCE_STATEMENT", "LOAN_PAYMENT",
    "EXTRA_REPAYMENT",
]

# Order is part of the prompt-cache prefix — keep it stable.
TOOLS = [
    {
        "name": "list_accounts",
        "description": "All accounts with id, name, type and institution.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "list_instruments",
        "description": (
            "Instruments (securities, crypto, metals, house, car) with id, name, "
            "ISIN, WKN and ticker. Optional search on name/ISIN/ticker."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"search": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_positions",
        "description": (
            "Current holdings per account and instrument as the ledger computes "
            "them: quantity, cost basis, current value. Optionally one account."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"account_id": {"type": "integer"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "list_transactions",
        "description": (
            "Booked transactions, newest first, with their ids. Filter by account, "
            "instrument and date range. Rows with provisional=true are estimates "
            "(e.g. booked automatically by a savings plan rule) waiting to be "
            "confirmed from a statement."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "instrument_id": {"type": "integer"},
                "from_date": _DATE,
                "to_date": _DATE,
                "limit": {"type": "integer", "description": "Default 50, max 200"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "list_recurring_bookings",
        "description": (
            "Standing rules (savings plans, loan instalment) that the app books "
            "automatically every month as provisional transactions with "
            "external_id recurring-<rule id>-<YYYY-MM>."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "propose_changes",
        "description": (
            "Propose ledger changes for the user to review. Nothing is written until "
            "the user applies the proposal in the app. The changes are validated "
            "immediately; on a validation error nothing is proposed and the error "
            "comes back so you can fix it. Group everything that belongs together "
            "(e.g. one statement) into one proposal."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "One or two sentences for the user, in their language.",
                },
                "creates": {
                    "type": "array",
                    "description": "New transactions.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": _DATE,
                            "type": {"type": "string", "enum": _TXN_TYPES},
                            "account_id": {"type": "integer"},
                            "instrument_id": {"type": "integer"},
                            "counter_account_id": {"type": "integer"},
                            "quantity": _DECIMAL,
                            "price": {**_DECIMAL, "description": "Per unit, native currency"},
                            "price_mode": {"type": "string", "enum": ["exact", "auto"]},
                            "amount": {
                                **_DECIMAL,
                                "description": "Flow amount for non-BUY/SELL types",
                            },
                            "currency": {"type": "string"},
                            "fx_rate": _DECIMAL,
                            "fees": _DECIMAL,
                            "tax": _DECIMAL,
                            "split_ratio": _DECIMAL,
                            "provisional": {"type": "boolean"},
                            "note": {"type": "string"},
                        },
                        "required": ["date", "type", "account_id", "currency"],
                        "additionalProperties": False,
                    },
                },
                "updates": {
                    "type": "array",
                    "description": (
                        "Corrections to existing transactions; only the fields given "
                        "change. Use this to confirm a provisional booking: real "
                        "quantity, price, fees, and provisional=false."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "transaction_id": {"type": "integer"},
                            "date": _DATE,
                            "quantity": _DECIMAL,
                            "price": _DECIMAL,
                            "fees": _DECIMAL,
                            "tax": _DECIMAL,
                            "note": {"type": "string"},
                            "provisional": {"type": "boolean"},
                        },
                        "required": ["transaction_id"],
                        "additionalProperties": False,
                    },
                },
                "deletes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "transaction_id": {"type": "integer"},
                            "reason": {"type": "string"},
                        },
                        "required": ["transaction_id", "reason"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["summary"],
            "additionalProperties": False,
        },
    },
]


class ProposalInvalid(Exception):
    def __init__(self, error: dict):
        self.error = error
        super().__init__(error.get("code"))


def _txn_view(txn: Txn) -> dict:
    data = TransactionRead.model_validate(txn).model_dump(mode="json")
    keep = (
        "id", "external_id", "date", "type", "account_id", "instrument_id",
        "quantity", "price", "currency", "fees", "tax", "amount_eur", "provisional", "note",
    )
    return {k: data[k] for k in keep}


def _list_accounts(db: Session, _: dict) -> list[dict]:
    return [
        {"id": a.id, "name": a.name, "type": a.type.value, "institution": a.institution,
         "archived": a.archived}
        for a in db.query(Account).order_by(Account.id)
    ]


def _list_instruments(db: Session, args: dict) -> list[dict]:
    query = db.query(Instrument)
    if args.get("search"):
        like = f"%{args['search']}%"
        query = query.filter(
            Instrument.name.ilike(like) | Instrument.isin.ilike(like) | Instrument.ticker.ilike(like)
        )
    return [
        {"id": i.id, "name": i.name, "isin": i.isin, "wkn": i.wkn, "ticker": i.ticker,
         "asset_class": i.asset_class.value, "currency": i.currency}
        for i in query.order_by(Instrument.name)
    ]


def _get_positions(db: Session, args: dict) -> list[dict]:
    names = {i.id: i.name for i in db.query(Instrument)}
    rows = get_positions(account_id=args.get("account_id"), group_by="account", db=db, _scope=None)
    return [
        {**r.model_dump(mode="json"), "instrument_name": names.get(r.instrument_id)}
        for r in rows
        if r.quantity != 0
    ]


def _list_transactions(db: Session, args: dict) -> list[dict]:
    query = db.query(Txn).filter(Txn.voided_at.is_(None))
    if args.get("account_id") is not None:
        query = query.filter(Txn.account_id == args["account_id"])
    if args.get("instrument_id") is not None:
        query = query.filter(Txn.instrument_id == args["instrument_id"])
    if args.get("from_date"):
        query = query.filter(Txn.date >= date.fromisoformat(args["from_date"]))
    if args.get("to_date"):
        query = query.filter(Txn.date <= date.fromisoformat(args["to_date"]))
    limit = max(1, min(int(args.get("limit") or 50), 200))
    rows = query.order_by(Txn.date.desc(), Txn.id.desc()).limit(limit)
    return [_txn_view(t) for t in rows]


def _list_recurring_bookings(db: Session, _: dict) -> list[dict]:
    return [
        {"id": r.id, "name": r.name, "type": r.type.value, "account_id": r.account_id,
         "instrument_id": r.instrument_id,
         "amount_eur": str(r.amount_eur) if r.amount_eur is not None else None,
         "fees": str(r.fees), "day_of_month": r.day_of_month,
         "shift_to_business_day": r.shift_to_business_day, "active": r.active,
         "booked_through": r.booked_through.isoformat() if r.booked_through else None}
        for r in db.query(RecurringBooking).order_by(RecurringBooking.id)
    ]


READ_TOOLS = {
    "list_accounts": _list_accounts,
    "list_instruments": _list_instruments,
    "get_positions": _get_positions,
    "list_transactions": _list_transactions,
    "list_recurring_bookings": _list_recurring_bookings,
}


def run_read_tool(db: Session, name: str, args: dict) -> list[dict]:
    return READ_TOOLS[name](db, args)


def parse_changes(args: dict) -> AgentChanges:
    try:
        return AgentChanges.model_validate(args)
    except ValidationError as e:
        first = e.errors()[0]
        raise ProposalInvalid(
            {"code": "validation_error",
             "params": {"field": ".".join(str(p) for p in first["loc"]), "msg": first["msg"]}}
        )


def assign_external_ids(changes: AgentChanges) -> list[str]:
    return [f"agent-{uuid.uuid4().hex[:12]}" for _ in changes.creates]


def _names(db: Session, account_id: int | None, instrument_id: int | None) -> dict:
    account = db.get(Account, account_id) if account_id else None
    instrument = db.get(Instrument, instrument_id) if instrument_id else None
    return {
        "account_name": account.name if account else None,
        "instrument_name": instrument.name if instrument else None,
    }


def apply_changes(
    db: Session, changes: AgentChanges, external_ids: list[str], batch_label: str
) -> tuple[int | None, list[dict]]:
    """Writes every change into `db` (flushed, not committed) and returns
    (import batch id, preview rows). Raises ProposalInvalid on the first
    change that fails, naming it; the caller must roll back."""
    preview: list[dict] = []
    batch_id = None
    if changes.creates:
        batch = ImportBatch(label=batch_label[:200], source=TxnSource.AGENT)
        db.add(batch)
        db.flush()
        batch_id = batch.id

    def fail(action: str, index: int, code: str, params: dict):
        raise ProposalInvalid({"code": code, "params": {**params, "action": action, "index": index}})

    for i, (item, external_id) in enumerate(zip(changes.creates, external_ids)):
        if db.query(Txn.id).filter(Txn.external_id == external_id).first():
            fail("create", i, "external_id_conflict", {"external_id": external_id})
        payload = TransactionCreate(
            external_id=external_id, source=TxnSource.AGENT, **item.model_dump()
        )
        try:
            txn = create_txn(db, payload, batch_id)
        except TxnValidationError as e:
            fail("create", i, e.code, e.params)
        preview.append(
            {"action": "create", "after": _txn_view(txn),
             **_names(db, txn.account_id, txn.instrument_id)}
        )

    for i, item in enumerate(changes.updates):
        txn = db.get(Txn, item.transaction_id)
        if txn is None:
            fail("update", i, "transaction_not_found", {"id": item.transaction_id})
        before = _txn_view(txn)
        body = TransactionUpdate(
            **item.model_dump(exclude_unset=True, exclude_none=True, exclude={"transaction_id"})
        )
        try:
            patch_txn(db, txn, body, actor=TxnSource.AGENT)
            db.flush()
        except TxnValidationError as e:
            fail("update", i, e.code, e.params)
        preview.append(
            {"action": "update", "before": before, "after": _txn_view(txn),
             **_names(db, txn.account_id, txn.instrument_id)}
        )

    for i, item in enumerate(changes.deletes):
        txn = db.get(Txn, item.transaction_id)
        if txn is None:
            fail("delete", i, "transaction_not_found", {"id": item.transaction_id})
        before = _txn_view(txn)
        names = _names(db, txn.account_id, txn.instrument_id)
        try:
            delete_txn(db, txn, actor=TxnSource.AGENT)
        except TxnValidationError as e:
            fail("delete", i, e.code, e.params)
        preview.append({"action": "delete", "before": before, "reason": item.reason, **names})

    db.flush()
    return batch_id, preview


def dry_run(changes: AgentChanges, external_ids: list[str]) -> list[dict]:
    """apply_changes in a throwaway session, always rolled back."""
    db = SessionLocal()
    try:
        _, preview = apply_changes(db, changes, external_ids, "dry run")
        return preview
    finally:
        db.rollback()
        db.close()


def tool_result_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
