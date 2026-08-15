from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("SELECT 1"))
        database_reachable = True
    except Exception:
        database_reachable = False

    return {
        "status": "ok" if database_reachable else "degraded",
        "database": "reachable" if database_reachable else "unreachable",
        # Populated once the relevant subsystems exist:
        # last successful price fetch (phase 2), last snapshot (phase 2),
        # last backup (host cron, ADR 0009/0012).
        "last_price_fetch": None,
        "last_snapshot": None,
        "last_backup": None,
    }
