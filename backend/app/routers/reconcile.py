from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import get_scope
from app.database import get_db
from app.models import Account, Instrument
from app.reconcile_service import compute_holdings_as_of
from app.schemas import ReconcileDifference, ReconcileRequest, ReconcileResponse

router = APIRouter(prefix="/api/reconcile", tags=["reconcile"])


@router.post("", response_model=ReconcileResponse)
def reconcile(
    body: ReconcileRequest,
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> ReconcileResponse:
    account = (
        db.query(Account)
        .filter(func.lower(Account.name) == body.account.lower())
        .first()
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "account_not_found", "params": {"account": body.account}},
        )

    computed = compute_holdings_as_of(db, account.id, body.as_of)

    reported_isins = [h.isin for h in body.holdings]
    instruments_by_isin = {
        i.isin: i
        for i in db.query(Instrument).filter(Instrument.isin.in_(reported_isins)).all()
    }

    differences: list[ReconcileDifference] = []
    seen_instrument_ids: set[int] = set()

    for holding in body.holdings:
        instrument = instruments_by_isin.get(holding.isin)
        if instrument is None:
            differences.append(
                ReconcileDifference(
                    isin=holding.isin,
                    instrument_id=None,
                    instrument_name=None,
                    reported_quantity=holding.quantity,
                    computed_quantity=Decimal(0),
                    delta=holding.quantity,
                    matched=False,
                    note="unknown_isin",
                )
            )
            continue
        seen_instrument_ids.add(instrument.id)
        computed_qty = computed.get(instrument.id, Decimal(0))
        delta = holding.quantity - computed_qty
        differences.append(
            ReconcileDifference(
                isin=holding.isin,
                instrument_id=instrument.id,
                instrument_name=instrument.name,
                reported_quantity=holding.quantity,
                computed_quantity=computed_qty,
                delta=delta,
                matched=delta == 0,
            )
        )

    # Held per the ledger but absent from the statement entirely — as
    # informative as a quantity mismatch (e.g. a position that should
    # have been closed out but wasn't, per the statement).
    if computed:
        instruments_by_id = {
            i.id: i
            for i in db.query(Instrument)
            .filter(Instrument.id.in_(computed.keys()))
            .all()
        }
        for instrument_id, computed_qty in computed.items():
            if instrument_id in seen_instrument_ids or computed_qty == 0:
                continue
            instrument = instruments_by_id.get(instrument_id)
            differences.append(
                ReconcileDifference(
                    isin=instrument.isin if instrument else None,
                    instrument_id=instrument_id,
                    instrument_name=instrument.name if instrument else None,
                    reported_quantity=None,
                    computed_quantity=computed_qty,
                    delta=-computed_qty,
                    matched=False,
                    note="missing_from_report",
                )
            )

    return ReconcileResponse(
        account_id=account.id, as_of=body.as_of, differences=differences
    )
