"""Manual entry for cpi_index_point (spec 4.6). A real Destatis GENESIS
fetch job is NOT implemented here, same story as house_index.py: their
API needs a one-off account registration only you can complete. Enter
annual CPI values by hand until that exists; the real-vs-nominal wealth
curve (timeseries.py) reads from this same table either way.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_scope, require_write_scope
from app.database import get_db
from app.models import CpiIndexPoint
from app.schemas import CpiIndexPointCreate, CpiIndexPointRead

router = APIRouter(prefix="/api/cpi", tags=["cpi"])


@router.post("", response_model=CpiIndexPointRead, status_code=201)
def upsert_cpi_point(
    body: CpiIndexPointCreate,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> CpiIndexPoint:
    existing = db.get(CpiIndexPoint, body.date)
    if existing:
        existing.index_value = body.index_value
        db.commit()
        db.refresh(existing)
        return existing
    row = CpiIndexPoint(**body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("", response_model=list[CpiIndexPointRead])
def list_cpi_points(
    db: Session = Depends(get_db), _scope=Depends(get_scope)
) -> list[CpiIndexPoint]:
    return db.query(CpiIndexPoint).order_by(CpiIndexPoint.date).all()
