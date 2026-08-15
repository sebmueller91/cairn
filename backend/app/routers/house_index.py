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

from app.auth import get_scope, require_write_scope
from app.database import get_db
from app.models import HousePriceIndexPoint
from app.schemas import HouseIndexPointCreate, HouseIndexPointRead

router = APIRouter(prefix="/api/house-index", tags=["house-index"])


@router.post("", response_model=HouseIndexPointRead, status_code=201)
def upsert_index_point(
    body: HouseIndexPointCreate,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> HousePriceIndexPoint:
    existing = db.get(HousePriceIndexPoint, (body.series, body.date))
    if existing:
        existing.index_value = body.index_value
        db.commit()
        db.refresh(existing)
        return existing
    row = HousePriceIndexPoint(**body.model_dump())
    db.add(row)
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
