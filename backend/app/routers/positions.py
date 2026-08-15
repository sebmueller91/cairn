from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_scope
from app.database import get_db
from app.ledger import TxnEvent, compute_positions, txn_to_event
from app.models import FxRate, Instrument, PricePoint, Txn
from app.schemas import PositionRead

router = APIRouter(prefix="/api/positions", tags=["positions"])


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
    """Same "latest price, convert via latest FX" idea as the snapshot
    engine's carry-forward lookup, but for a single as-of-today point
    rather than a full daily walk — MARKET instruments only, same
    phase-2 scope boundary as everywhere else this quarter touches
    valuation."""
    if instrument is None or instrument.valuation_mode != "MARKET":
        return None
    price_point = (
        db.query(PricePoint)
        .filter(PricePoint.instrument_id == instrument.id)
        .order_by(PricePoint.date.desc())
        .first()
    )
    if price_point is None:
        return None
    if instrument.currency == "EUR":
        fx = Decimal(1)
    else:
        fx_row = (
            db.query(FxRate)
            .filter(FxRate.currency == instrument.currency)
            .order_by(FxRate.date.desc())
            .first()
        )
        if fx_row is None:
            return None
        fx = fx_row.eur_rate
    return quantity * price_point.close * fx


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
