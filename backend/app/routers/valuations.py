from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_scope, require_write_scope
from app.database import get_db
from app.models import Instrument, ValuationAnchor
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
