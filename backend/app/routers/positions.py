from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_scope
from app.database import get_db
from app.db_types import quantize_money
from app.ledger import TxnEvent, compute_positions, txn_to_event
from app.models import Instrument, Txn, ValuationMode
from app.schemas import PositionRead
from app.valuation_service import current_instrument_value

router = APIRouter(prefix="/api/positions", tags=["positions"])

VALID_GROUP_BY = ("account", "instrument")


def _load_events(db: Session, account_id: int | None) -> list[TxnEvent]:
    query = db.query(Txn).filter(Txn.voided_at.is_(None), Txn.instrument_id.isnot(None))
    if account_id is not None:
        query = query.filter(
            (Txn.account_id == account_id) | (Txn.counter_account_id == account_id)
        )
    return [txn_to_event(t) for t in query.all()]


def _latest_value_eur(
    db: Session, instrument: Instrument | None, quantity: Decimal
) -> Decimal | None:
    """MARKET is a per-unit price (multiply by quantity held); ANCHORED/
    MODELED (house/car) is already the value of the whole holding, since
    a house is never fractionally owned the way a share position is —
    quantity there is always 1 and multiplying again would be wrong."""
    if instrument is None:
        return None
    value = current_instrument_value(db, instrument.id, date.today())
    if value is None:
        return None
    if instrument.valuation_mode == ValuationMode.MARKET:
        return quantize_money(quantity * value)
    return quantize_money(value)


@router.get("", response_model=list[PositionRead])
def get_positions(
    account_id: int | None = None,
    group_by: str = "account",
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> list[PositionRead]:
    if group_by not in VALID_GROUP_BY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_group_by", "params": {"group_by": group_by}},
        )
    # SPLIT and TRANSFER touch lots outside a single account's own history
    # (a split is an instrument-wide corporate action; a transfer moves
    # lots between two accounts) — always replay the instrument's full
    # cross-account history, then filter the *result* to account_id if
    # one was requested. Filtering the input events instead would silently
    # miscompute a position by missing the other side of a transfer.
    events = _load_events(db, account_id=None)
    positions = compute_positions(events)
    instruments = {i.id: i for i in db.query(Instrument).all()}

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
        results = []
        for instrument_id, values in totals.items():
            value_eur = _latest_value_eur(db, instruments.get(instrument_id), values["quantity"])
            unrealized = value_eur - values["cost_basis_eur"] if value_eur is not None else None
            results.append(
                PositionRead(
                    account_id=None,
                    instrument_id=instrument_id,
                    value_eur=value_eur,
                    unrealized_pl_eur=unrealized,
                    **values,
                )
            )
        return results

    results = []
    for (acc_id, instrument_id), pos in positions.items():
        if account_id is not None and acc_id != account_id:
            continue
        value_eur = _latest_value_eur(db, instruments.get(instrument_id), pos.quantity)
        unrealized = value_eur - pos.cost_basis_eur if value_eur is not None else None
        results.append(
            PositionRead(
                account_id=pos.account_id,
                instrument_id=pos.instrument_id,
                quantity=pos.quantity,
                cost_basis_eur=pos.cost_basis_eur,
                realized_pl_eur=pos.realized_pl_eur,
                value_eur=value_eur,
                unrealized_pl_eur=unrealized,
            )
        )
    return results
