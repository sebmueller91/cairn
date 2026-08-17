from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import audit
from app.auth import get_scope, require_write_scope
from app.database import get_db
from app.look_through_service import compute_look_through
from app.models import EtfComposition, Instrument, TxnSource
from app.schemas import (
    EtfCompositionRow,
    EtfCompositionSet,
    LookThroughResponse,
    LookThroughRowRead,
)

router = APIRouter(prefix="/api", tags=["look-through"])


@router.put("/instruments/{instrument_id}/composition", response_model=list[EtfCompositionRow])
def set_composition(
    instrument_id: int,
    body: EtfCompositionSet,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> list[EtfComposition]:
    """Replaces the full breakdown for one (instrument, dimension) pair —
    "entered by hand from the factsheet" (spec 4.4) means pasting in the
    whole thing at once, not editing rows one at a time."""
    if db.get(Instrument, instrument_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "instrument_not_found", "params": {"id": instrument_id}},
        )
    db.query(EtfComposition).filter(
        EtfComposition.instrument_id == instrument_id,
        EtfComposition.dimension == body.dimension,
    ).delete()
    entered_at = datetime.now(UTC).replace(tzinfo=None)
    rows = [
        EtfComposition(
            instrument_id=instrument_id, dimension=body.dimension, category=category,
            weight_pct=weight, updated_at=entered_at,
        )
        for category, weight in body.breakdown.items()
    ]
    db.add_all(rows)
    # A replace-all write, not a per-row create — one audit record for the
    # whole new state. This router has no source field to distinguish
    # agent vs. manual UI use — both arrive over the same bearer/cookie
    # auth — so it's logged as TxnSource.AGENT, same as transactions.py's
    # PATCH/DELETE.
    audit.record(
        db,
        actor=TxnSource.AGENT,
        action="update",
        entity="etf_composition",
        entity_id=instrument_id,
        payload_hash="n/a",
        diff={"dimension": body.dimension, "breakdown": {k: str(v) for k, v in body.breakdown.items()}},
    )
    db.commit()
    return rows


@router.get("/instruments/{instrument_id}/composition", response_model=list[EtfCompositionRow])
def get_composition(
    instrument_id: int, db: Session = Depends(get_db), _scope=Depends(get_scope)
) -> list[EtfComposition]:
    return (
        db.query(EtfComposition)
        .filter(EtfComposition.instrument_id == instrument_id)
        .order_by(EtfComposition.dimension, EtfComposition.category)
        .all()
    )


@router.get("/look-through", response_model=LookThroughResponse)
def get_look_through(
    dimension: str = "region",
    # Historical breakdown as of a past date, same convention as
    # look_through_service.compute_look_through's own default of today.
    as_of: date | None = None,
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> LookThroughResponse:
    rows = compute_look_through(db, dimension, as_of=as_of)
    return LookThroughResponse(
        dimension=dimension,
        rows=[LookThroughRowRead(category=r.category, value_eur=r.value_eur) for r in rows],
    )
