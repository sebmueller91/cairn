from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import audit
from app.auth import get_scope, require_write_scope
from app.database import get_db
from app.models import Instrument, TxnSource, ValuationAnchor
from app.schemas import ValuationAnchorCreate, ValuationAnchorRead

router = APIRouter(prefix="/api/valuations", tags=["valuations"])


@router.post("", response_model=ValuationAnchorRead, status_code=status.HTTP_201_CREATED)
def create_valuation_anchor(
    body: ValuationAnchorCreate,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> ValuationAnchor:
    instrument = db.get(Instrument, body.instrument_id)
    if instrument is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "instrument_not_found", "params": {"id": body.instrument_id}},
        )
    if instrument.valuation_mode not in ("ANCHORED", "MODELED"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "valuation_mode_has_no_anchors",
                "params": {"valuation_mode": instrument.valuation_mode.value},
            },
        )
    anchor = ValuationAnchor(**body.model_dump())
    db.add(anchor)
    db.flush()  # assigns anchor.id, needed for the audit record
    # This router has no source field to distinguish agent vs. manual UI
    # use — both arrive over the same bearer/cookie auth — so this write
    # is logged as TxnSource.AGENT, same as transactions.py's PATCH/DELETE.
    audit.record(
        db,
        actor=TxnSource.AGENT,
        action="create",
        entity="valuation_anchor",
        entity_id=anchor.id,
        payload_hash="n/a",
    )
    db.commit()
    db.refresh(anchor)
    return anchor


@router.get("", response_model=list[ValuationAnchorRead])
def list_valuation_anchors(
    instrument_id: int,
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> list[ValuationAnchor]:
    return (
        db.query(ValuationAnchor)
        .filter(ValuationAnchor.instrument_id == instrument_id)
        .order_by(ValuationAnchor.date)
        .all()
    )
