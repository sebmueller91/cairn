from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import kv_store
from app.auth import require_write_scope
from app.database import get_db
from app.schemas import RebuildSnapshotsResponse
from app.snapshot_service import rebuild_snapshots

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/rebuild-snapshots", response_model=RebuildSnapshotsResponse)
def trigger_rebuild_snapshots(
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> RebuildSnapshotsResponse:
    days = rebuild_snapshots(db)
    kv_store.set(db, "last_snapshot", datetime.now(UTC).replace(tzinfo=None).isoformat())
    db.commit()
    return RebuildSnapshotsResponse(days_written=days)
