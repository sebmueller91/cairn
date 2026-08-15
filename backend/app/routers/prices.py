from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import kv_store
from app.auth import require_write_scope
from app.database import get_db
from app.models import Instrument
from app.price_fetch_service import (
    backfill_for_instrument,
    fetch_all_fx_rates,
    fetch_fx_rate,
    fetch_latest_for_instrument,
)
from app.schemas import (
    FetchResultRead,
    PriceBackfillRequest,
    PriceFetchResponse,
    PriceRefreshRequest,
)

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.post("/refresh", response_model=PriceFetchResponse)
def refresh_prices(
    body: PriceRefreshRequest,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> PriceFetchResponse:
    if body.instrument_id is not None:
        instrument = db.get(Instrument, body.instrument_id)
        if instrument is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "instrument_not_found",
                    "params": {"id": body.instrument_id},
                },
            )
        instruments = [instrument]
        # Single-instrument refresh: only that instrument's own currency
        # needs a fresh FX rate (fetch_fx_rate is itself a no-op for EUR).
        fx_results = [fetch_fx_rate(db, instrument.currency)] if instrument.currency != "EUR" else []
    else:
        instruments = db.query(Instrument).all()
        fx_results = fetch_all_fx_rates(db)

    results = [fetch_latest_for_instrument(db, i) for i in instruments]
    all_results = results + fx_results
    if any(r.status == "ok" for r in all_results):
        kv_store.set(
            db, "last_price_fetch", datetime.now(UTC).replace(tzinfo=None).isoformat()
        )
    db.commit()
    return PriceFetchResponse(
        results=[
            # instrument_id=0 on fx_results entries is the FX sentinel
            # (see fetch_fx_rate); FetchResultRead's shape is unchanged,
            # detail carries the currency for those rows.
            FetchResultRead(instrument_id=r.instrument_id, status=r.status, detail=r.detail)
            for r in all_results
        ]
    )


@router.post("/backfill", response_model=PriceFetchResponse)
def backfill_prices(
    body: PriceBackfillRequest,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> PriceFetchResponse:
    instrument = db.get(Instrument, body.instrument_id)
    if instrument is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "instrument_not_found", "params": {"id": body.instrument_id}},
        )
    start = body.start or date(1990, 1, 1)
    end = body.end or date.today()
    result = backfill_for_instrument(db, instrument, start, end)
    db.commit()
    return PriceFetchResponse(
        results=[FetchResultRead(instrument_id=result.instrument_id, status=result.status, detail=result.detail)]
    )
