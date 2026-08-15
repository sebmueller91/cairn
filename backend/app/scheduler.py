"""In-process scheduled jobs (ADR 0009): price fetch and snapshot rebuild
run here, inside the API container, because they need the ORM/service
layer directly. Backup deliberately does NOT run here — see ADR 0009 for
why coupling backup's schedule to this process's liveness would be the
wrong failure mode.
"""

import logging
from datetime import UTC, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import kv_store
from app.database import SessionLocal
from app.models import Instrument
from app.price_fetch_service import fetch_all_fx_rates, fetch_latest_for_instrument
from app.snapshot_service import rebuild_snapshots

logger = logging.getLogger(__name__)

BERLIN = "Europe/Berlin"


def run_price_fetch_job() -> None:
    db = SessionLocal()
    try:
        instruments = db.query(Instrument).all()
        results = [fetch_latest_for_instrument(db, i) for i in instruments]
        # FX rates alongside instrument prices — the 23:00 snapshot rebuild
        # needs both, since non-EUR positions are valued via fx_rate.
        fx_results = fetch_all_fx_rates(db)
        if any(r.status == "ok" for r in results + fx_results):
            kv_store.set(
                db, "last_price_fetch", datetime.now(UTC).replace(tzinfo=None).isoformat()
            )
        db.commit()
        logger.info(
            "price fetch job: %d/%d instruments ok, %d/%d fx rates ok",
            sum(1 for r in results if r.status == "ok"),
            len(results),
            sum(1 for r in fx_results if r.status == "ok"),
            len(fx_results),
        )
    except Exception:
        db.rollback()
        logger.exception("price fetch job failed")
    finally:
        db.close()


def run_snapshot_rebuild_job() -> None:
    db = SessionLocal()
    try:
        days = rebuild_snapshots(db)
        kv_store.set(db, "last_snapshot", datetime.now(UTC).replace(tzinfo=None).isoformat())
        db.commit()
        logger.info("snapshot rebuild job: %d days written", days)
    except Exception:
        db.rollback()
        logger.exception("snapshot rebuild job failed")
    finally:
        db.close()


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=BERLIN)
    # EOD price fetch first (spec 5), snapshot rebuild after so the
    # rebuild has the day's prices available.
    scheduler.add_job(
        run_price_fetch_job,
        CronTrigger(hour=22, minute=30, timezone=BERLIN),
        id="price_fetch",
        replace_existing=True,
    )
    scheduler.add_job(
        run_snapshot_rebuild_job,
        CronTrigger(hour=23, minute=0, timezone=BERLIN),
        id="snapshot_rebuild",
        replace_existing=True,
    )
    return scheduler
