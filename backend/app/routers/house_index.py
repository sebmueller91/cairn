"""Manual entry for house_price_index_point (spec 3.4). A real Destatis
GENESIS fetch job is NOT implemented here: their API redirects to an
auth-gated endpoint and genuinely requires a one-off account registration
(confirmed by hand, not assumed) — something only you can do, not
something to fake or stub as if it worked. Enter quarterly index values
by hand here until that's set up; the house valuation model (already
live) reads from this same table either way, so nothing else changes
once a real fetch job exists.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import audit
from app.auth import get_scope, require_write_scope
from app.database import get_db
from app.models import HousePriceIndexPoint, TxnSource
from app.schemas import HouseIndexPointCreate, HouseIndexPointRead

router = APIRouter(prefix="/api/house-index", tags=["house-index"])


@router.post("", response_model=HouseIndexPointRead, status_code=201)
def upsert_index_point(
    body: HouseIndexPointCreate,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> HousePriceIndexPoint:
    # This router has no source field to distinguish agent vs. manual UI
    # use — both arrive over the same bearer/cookie auth — so every write
    # here is logged as TxnSource.AGENT, same as transactions.py's
    # PATCH/DELETE. No single id on this table, so entity_id is the
    # composite "series:date" key.
    entity_id = f"{body.series}:{body.date}"
    existing = db.get(HousePriceIndexPoint, (body.series, body.date))
    if existing:
        before = str(existing.index_value)
        existing.index_value = body.index_value
        audit.record(
            db,
            actor=TxnSource.AGENT,
            action="update",
            entity="house_price_index_point",
            entity_id=entity_id,
            payload_hash="n/a",
            diff={"before": before, "after": str(body.index_value)},
        )
        db.commit()
        db.refresh(existing)
        return existing
    row = HousePriceIndexPoint(**body.model_dump())
    db.add(row)
    audit.record(
        db,
        actor=TxnSource.AGENT,
        action="create",
        entity="house_price_index_point",
        entity_id=entity_id,
        payload_hash="n/a",
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("", response_model=list[HouseIndexPointRead])
def list_index_points(
    series: str,
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> list[HousePriceIndexPoint]:
    return (
        db.query(HousePriceIndexPoint)
        .filter(HousePriceIndexPoint.series == series)
        .order_by(HousePriceIndexPoint.date)
        .all()
    )
