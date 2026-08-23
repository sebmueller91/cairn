from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import kv_store
from app.data_quality_service import STALE_PRICE_FETCH_HOURS, STALE_SNAPSHOT_HOURS
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


def _is_stale(raw: str | None, threshold_hours: int) -> bool:
    """Interpret one of the kv_store job timestamps (last_price_fetch,
    last_snapshot) against the same threshold data_quality_service.py uses
    for its stale_price_fetch_job/stale_snapshot_job issue kinds — this
    used to just echo the raw ISO string with no judgement at all, so a
    dead job produced no signal here (ADR 0009's named failure mode).
    Missing/unparseable counts as stale, same "never ran" convention the
    backup markers already use."""
    if not raw:
        return True
    try:
        last = datetime.fromisoformat(raw)
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    age_hours = (datetime.now(UTC) - last).total_seconds() / 3600
    return age_hours > threshold_hours


@router.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("SELECT 1"))
        database_reachable = True
    except Exception:
        database_reachable = False

    # Three trivial queries total (SELECT 1 above, plus these two
    # single-row kv_store lookups by primary key) — deliberately no new
    # query for the staleness judgement, it's computed from values already
    # fetched. `status` stays keyed to DB reachability only, matching how
    # the two backup markers below have always worked: they're surfaced as
    # raw values here and interpreted by the data-quality panel, not
    # folded into this endpoint's coarse ok/degraded field. A brand-new
    # deployment before its first nightly run is "never ran yet", not
    # "degraded" — that distinction belongs in the data-quality panel
    # (stale vs. missing kinds), not in a binary health status.
    last_price_fetch = kv_store.get(db, "last_price_fetch")
    last_snapshot = kv_store.get(db, "last_snapshot")

    return {
        "status": "ok" if database_reachable else "degraded",
        "database": "reachable" if database_reachable else "unreachable",
        "last_price_fetch": last_price_fetch,
        "last_price_fetch_stale": _is_stale(last_price_fetch, STALE_PRICE_FETCH_HOURS),
        "last_snapshot": last_snapshot,
        "last_snapshot_stale": _is_stale(last_snapshot, STALE_SNAPSHOT_HOURS),
        "last_backup": _read_marker(_LAST_SUCCESS_FILE),
        "last_offsite_backup": _read_marker(_LAST_OFFSITE_FILE),
    }
