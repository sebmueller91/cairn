from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import kv_store
from app.database import get_db

router = APIRouter(tags=["health"])

# Written by scripts/backup.sh on host cron (ADR 0009/0012) — deliberately
# not app-DB state, since the backup job runs independently of the API
# container's own lifecycle. Only ever updated on a fully clean run, so
# its own timestamp going stale *is* the failure signal, without needing
# a separate alert path (ADR 0012).
_LAST_SUCCESS_FILE = Path("/backup-status/last_success")
# The offsite (NAS) leg reports separately rather than folding into the
# marker above (ADR 0015). A NAS that is rebooting or asleep would
# otherwise make this endpoint report no backup at all on a night when
# the local one succeeded perfectly — and an offsite leg that quietly
# stopped would be invisible behind a healthy local one. Two markers,
# neither able to mask the other.
_LAST_OFFSITE_FILE = Path("/backup-status/last_offsite_success")


def _read_marker(path: Path) -> str | None:
    try:
        return path.read_text().strip() or None
    except FileNotFoundError:
        return None


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
        "last_backup": _read_marker(_LAST_SUCCESS_FILE),
        "last_offsite_backup": _read_marker(_LAST_OFFSITE_FILE),
    }
