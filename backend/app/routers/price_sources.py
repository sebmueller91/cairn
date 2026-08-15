from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_scope, require_write_scope
from app.database import get_db
from app.models import Instrument, PriceSource
from app.providers.registry import known_provider_names
from app.schemas import PriceSourceCreate, PriceSourceRead, PriceSourceUpdate

router = APIRouter(prefix="/api/instruments/{instrument_id}/price-sources", tags=["price-sources"])


def _get_instrument_or_404(db: Session, instrument_id: int) -> Instrument:
    instrument = db.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "instrument_not_found", "params": {"id": instrument_id}},
        )
    return instrument


@router.post("", response_model=PriceSourceRead, status_code=status.HTTP_201_CREATED)
def create_price_source(
    instrument_id: int,
    body: PriceSourceCreate,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> PriceSource:
    _get_instrument_or_404(db, instrument_id)
    known = known_provider_names()
    if body.provider not in known:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "unknown_price_provider",
                "params": {"provider": body.provider, "known": known},
            },
        )
    source = PriceSource(instrument_id=instrument_id, **body.model_dump())
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.get("", response_model=list[PriceSourceRead])
def list_price_sources(
    instrument_id: int,
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> list[PriceSource]:
    _get_instrument_or_404(db, instrument_id)
    return (
        db.query(PriceSource)
        .filter(PriceSource.instrument_id == instrument_id)
        .order_by(PriceSource.priority)
        .all()
    )


def _get_source_or_404(db: Session, instrument_id: int, source_id: int) -> PriceSource:
    source = db.get(PriceSource, source_id)
    if source is None or source.instrument_id != instrument_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "price_source_not_found", "params": {"id": source_id}},
        )
    return source


@router.patch("/{source_id}", response_model=PriceSourceRead)
def update_price_source(
    instrument_id: int,
    source_id: int,
    body: PriceSourceUpdate,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> PriceSource:
    source = _get_source_or_404(db, instrument_id, source_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(source, field, value)
    db.commit()
    db.refresh(source)
    return source


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_price_source(
    instrument_id: int,
    source_id: int,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> None:
    source = _get_source_or_404(db, instrument_id, source_id)
    db.delete(source)
    db.commit()
