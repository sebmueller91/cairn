import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_scope, require_write_scope
from app.database import get_db
from app.models import Instrument, PricePoint, PriceSource, Txn
from app.schemas import InstrumentCreate, InstrumentRead, InstrumentUpdate

router = APIRouter(prefix="/api/instruments", tags=["instruments"])


def _to_read(instrument: Instrument) -> InstrumentRead:
    return InstrumentRead(
        id=instrument.id,
        name=instrument.name,
        isin=instrument.isin,
        wkn=instrument.wkn,
        ticker=instrument.ticker,
        asset_class=instrument.asset_class,
        valuation_mode=instrument.valuation_mode,
        currency=instrument.currency,
        region=instrument.region,
        sector=instrument.sector,
        liquidity_tier=instrument.liquidity_tier,
        ter_pct=instrument.ter_pct,
        fine_weight_g=instrument.fine_weight_g,
        valuation_config=json.loads(instrument.valuation_config_json or "{}"),
        tags=json.loads(instrument.tags_json or "[]"),
        notes=instrument.notes,
        created_at=instrument.created_at,
        updated_at=instrument.updated_at,
    )


def _get_or_404(db: Session, instrument_id: int) -> Instrument:
    instrument = db.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "instrument_not_found", "params": {"id": instrument_id}},
        )
    return instrument


@router.post("", response_model=InstrumentRead, status_code=status.HTTP_201_CREATED)
def create_instrument(
    body: InstrumentCreate,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> InstrumentRead:
    data = body.model_dump(exclude={"valuation_config", "tags"})
    instrument = Instrument(
        **data,
        valuation_config_json=json.dumps(body.valuation_config),
        tags_json=json.dumps(body.tags),
    )
    db.add(instrument)
    db.commit()
    db.refresh(instrument)
    return _to_read(instrument)


@router.get("", response_model=list[InstrumentRead])
def list_instruments(
    search: str | None = None,
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> list[InstrumentRead]:
    query = db.query(Instrument)
    if search:
        like = f"%{search}%"
        query = query.filter(
            (Instrument.name.ilike(like))
            | (Instrument.isin.ilike(like))
            | (Instrument.ticker.ilike(like))
        )
    return [_to_read(i) for i in query.order_by(Instrument.name).all()]


@router.get("/{instrument_id}", response_model=InstrumentRead)
def get_instrument(
    instrument_id: int,
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> InstrumentRead:
    return _to_read(_get_or_404(db, instrument_id))


@router.patch("/{instrument_id}", response_model=InstrumentRead)
def update_instrument(
    instrument_id: int,
    body: InstrumentUpdate,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> InstrumentRead:
    instrument = _get_or_404(db, instrument_id)
    updates = body.model_dump(exclude_unset=True, exclude={"valuation_config", "tags"})
    for field, value in updates.items():
        setattr(instrument, field, value)
    if body.valuation_config is not None:
        instrument.valuation_config_json = json.dumps(body.valuation_config)
    if body.tags is not None:
        instrument.tags_json = json.dumps(body.tags)
    db.commit()
    db.refresh(instrument)
    return _to_read(instrument)


@router.delete("/{instrument_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_instrument(
    instrument_id: int,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> None:
    instrument = _get_or_404(db, instrument_id)
    has_txns = db.query(Txn).filter(Txn.instrument_id == instrument_id).first() is not None
    if has_txns:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "instrument_has_transactions",
                "params": {"instrument_id": instrument_id},
            },
        )
    # price_source (provider config) and price_point (fetched/cacheable
    # data, refetchable at any time) both FK to instrument with no ledger
    # significance — cascade-delete both rather than block, unlike
    # transactions. Checked every FK referencing instrument.id in
    # models.py this time, not just the one that happened to crash first.
    db.query(PriceSource).filter(PriceSource.instrument_id == instrument_id).delete()
    db.query(PricePoint).filter(PricePoint.instrument_id == instrument_id).delete()
    db.delete(instrument)
    db.commit()
