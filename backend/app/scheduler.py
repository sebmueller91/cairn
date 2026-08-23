"""In-process scheduled jobs (ADR 0009): price fetch and snapshot rebuild
run here, inside the API container, because they need the ORM/service
layer directly. Backup deliberately does NOT run here — see ADR 0009 for
why coupling backup's schedule to this process's liveness would be the
wrong failure mode.
"""

import logging
import sys
from datetime import UTC, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import kv_store
from app.database import SessionLocal
from app.models import Instrument
from app.price_fetch_service import (
    distinct_non_eur_currencies,
    fetch_fx_rate,
    fetch_latest_for_instrument,
)
from app.snapshot_service import rebuild_snapshots

logger = logging.getLogger(__name__)

BERLIN = "Europe/Berlin"

# A realistic grace window for a job that only needs to run once a night.
# APScheduler 3.x's own default is misfire_grace_time=1 *second* — a
# container that restarts at 22:29 and takes a few seconds past 22:30 to
# finish `alembic upgrade head` would otherwise have that night's run
# discarded outright rather than run a few seconds late. An hour is still
# nowhere near the next scheduled run (24h later), so there is no risk of
# double-running — max_instances=1 (below) would prevent that anyway.
MISFIRE_GRACE_SECONDS = 3600


def configure_app_logging() -> None:
    """Make `app.*` logging (job start/finish, per-instrument failures)
    actually reach stdout with timestamps.

    There is no `logging.basicConfig` anywhere in this codebase. Uvicorn's
    own LOGGING_CONFIG (see `uvicorn.config`) only configures the
    `uvicorn`/`uvicorn.access`/`uvicorn.error` loggers — root is left at
    WARNING with no handler attached, so `logger.info(...)` calls in this
    module (and anywhere else under `app.*`) are silently dropped, and
    `logger.exception(...)` only escapes via `logging.lastResort`,
    unformatted and untimestamped. ADR 0009 names "a job silently
    stopping without anyone noticing" as exactly the failure mode to
    design against — a job that ran fine but left no trace is a milder
    version of the same problem.

    This attaches a handler directly to the "app" logger (the shared
    ancestor of "app.scheduler", "app.price_fetch_service", etc.) rather
    than touching the root logger, so it can't be silently reconfigured
    by uvicorn's own dictConfig call (which explicitly sets
    `disable_existing_loggers: False` and never mentions "app", so this
    is safe regardless of import order). Propagation to root is left at
    its default (True): root has no handler of its own — uvicorn's
    LOGGING_CONFIG never touches it — so records still bubble up for
    anything that inspects the root logger (e.g. pytest's `caplog`)
    without ever risking a duplicate line, since there is no root handler
    to double-print through. Idempotent: safe to call more than once
    (tests import this module repeatedly).
    """
    app_logger = logging.getLogger("app")
    if app_logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)


def _now_iso() -> str:
    # Offset-aware, unlike the previous `.replace(tzinfo=None)`. The NAS
    # backup's own markers (scripts/backup.sh, `date -Iseconds`) are
    # timezone-aware local time; a naive kv timestamp next to those made
    # the frontend (which parses an offset-less date-time as *local*, not
    # UTC) read last_price_fetch/last_snapshot as two hours older than
    # reality in CEST. Both conventions should be unambiguous, not just
    # one of them.
    return datetime.now(UTC).isoformat()


def run_price_fetch_job() -> None:
    db = SessionLocal()
    try:
        instruments = db.query(Instrument).all()
        ok = 0
        for instrument in instruments:
            try:
                result = fetch_latest_for_instrument(db, instrument)
                db.commit()
            except Exception:
                # fetch_latest_for_instrument only catches ProviderError
                # internally — anything else (a provider bug, a bad JSON
                # shape a provider adapter didn't anticipate) used to
                # escape the old single list-comprehension, roll back
                # *every* instrument's writes committed so far in this
                # run via the one `db.rollback()` at the bottom, and
                # abort before last_price_fetch was ever updated. One bad
                # symbol must not discard the whole night: commit (or
                # roll back) per instrument, log, and move on.
                db.rollback()
                logger.exception(
                    "price fetch job: instrument %s raised unexpectedly, skipped",
                    instrument.id,
                )
                continue
            if result.status == "ok":
                ok += 1

        # FX rates alongside instrument prices — the 23:00 snapshot
        # rebuild needs both, since non-EUR positions are valued via
        # fx_rate. Same per-currency isolation as above, for the same
        # reason.
        fx_ok = 0
        currencies = distinct_non_eur_currencies(db)
        for currency in currencies:
            try:
                fx_result = fetch_fx_rate(db, currency)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception(
                    "price fetch job: fx rate %s raised unexpectedly, skipped", currency
                )
                continue
            if fx_result.status == "ok":
                fx_ok += 1

        if ok > 0 or fx_ok > 0:
            kv_store.set(db, "last_price_fetch", _now_iso())
            db.commit()
        logger.info(
            "price fetch job: %d/%d instruments ok, %d/%d fx rates ok",
            ok,
            len(instruments),
            fx_ok,
            len(currencies),
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
        kv_store.set(db, "last_snapshot", _now_iso())
        db.commit()
        logger.info("snapshot rebuild job: %d days written", days)
    except Exception:
        db.rollback()
        logger.exception("snapshot rebuild job failed")
    finally:
        db.close()


def create_scheduler() -> BackgroundScheduler:
    configure_app_logging()
    scheduler = BackgroundScheduler(timezone=BERLIN)
    # EOD price fetch first (spec 5), snapshot rebuild after so the
    # rebuild has the day's prices available.
    scheduler.add_job(
        run_price_fetch_job,
        CronTrigger(hour=22, minute=30, timezone=BERLIN),
        id="price_fetch",
        replace_existing=True,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
        coalesce=True,
        # Correct already, kept explicit: a run that is still going must
        # never overlap with the next night's trigger.
        max_instances=1,
    )
    scheduler.add_job(
        run_snapshot_rebuild_job,
        CronTrigger(hour=23, minute=0, timezone=BERLIN),
        id="snapshot_rebuild",
        replace_existing=True,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
        coalesce=True,
        max_instances=1,
    )
    return scheduler
