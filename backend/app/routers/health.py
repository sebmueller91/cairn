from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import kv_store
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
        "last_price_fetch": kv_store.get(db, "last_price_fetch"),
        "last_snapshot": kv_store.get(db, "last_snapshot"),
        # Populated by host cron writing to this same table once the
        # backup script exists (ADR 0009/0012) — not an app-level job.
        "last_backup": None,
    }
