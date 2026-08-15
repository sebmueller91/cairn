from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_scope
from app.database import get_db
from app.ledger import TxnEvent, compute_positions, txn_to_event
from app.models import Txn
from app.schemas import PositionRead

router = APIRouter(prefix="/api/positions", tags=["positions"])


def _load_events(db: Session, account_id: int | None) -> list[TxnEvent]:
    query = db.query(Txn).filter(Txn.voided_at.is_(None), Txn.instrument_id.isnot(None))
    if account_id is not None:
        query = query.filter(
            (Txn.account_id == account_id) | (Txn.counter_account_id == account_id)
        )
    return [txn_to_event(t) for t in query.all()]


@router.get("", response_model=list[PositionRead])
def get_positions(
    account_id: int | None = None,
    group_by: str = "account",
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> list[PositionRead]:
    # SPLIT and TRANSFER touch lots outside a single account's own history
    # (a split is an instrument-wide corporate action; a transfer moves
    # lots between two accounts) — always replay the instrument's full
    # cross-account history, then filter the *result* to account_id if
    # one was requested. Filtering the input events instead would silently
    # miscompute a position by missing the other side of a transfer.
    events = _load_events(db, account_id=None)
    positions = compute_positions(events)

    if group_by == "instrument":
        totals: dict[int, dict[str, Decimal]] = defaultdict(
            lambda: {"quantity": Decimal(0), "cost_basis_eur": Decimal(0), "realized_pl_eur": Decimal(0)}
        )
        for (acc_id, instrument_id), pos in positions.items():
            if account_id is not None and acc_id != account_id:
                continue
            totals[instrument_id]["quantity"] += pos.quantity
            totals[instrument_id]["cost_basis_eur"] += pos.cost_basis_eur
            totals[instrument_id]["realized_pl_eur"] += pos.realized_pl_eur
        return [
            PositionRead(account_id=None, instrument_id=instrument_id, **values)
            for instrument_id, values in totals.items()
        ]

    return [
        PositionRead(
            account_id=pos.account_id,
            instrument_id=pos.instrument_id,
            quantity=pos.quantity,
            cost_basis_eur=pos.cost_basis_eur,
            realized_pl_eur=pos.realized_pl_eur,
        )
        for (acc_id, instrument_id), pos in positions.items()
        if account_id is None or acc_id == account_id
    ]
