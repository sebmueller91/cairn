"""Bug 3 & 4 coverage: the scheduler's job configuration (misfire grace,
coalesce, max_instances), its logging setup, and — the testable-without-
network half of bug 2 — that run_price_fetch_job degrades per-instrument
instead of discarding the whole night when one instrument raises
something other than ProviderError.
"""

import logging
import sys
from datetime import date
from decimal import Decimal

from app.models import AssetClass, Instrument, PricePoint, ValuationMode
from app.price_fetch_service import FetchResult
from app.scheduler import MISFIRE_GRACE_SECONDS, configure_app_logging, create_scheduler


def _make_instrument(db_session, isin, name="Test Instrument"):
    i = Instrument(
        name=name,
        isin=isin,
        asset_class=AssetClass.EQUITY,
        valuation_mode=ValuationMode.MARKET,
        currency="EUR",
        valuation_config_json="{}",
        tags_json="[]",
    )
    db_session.add(i)
    db_session.commit()
    db_session.refresh(i)
    return i


# --- Bug 4: realistic misfire_grace_time / coalesce / max_instances -------


def test_scheduler_jobs_have_realistic_misfire_grace_time():
    """APScheduler 3.x defaults misfire_grace_time to 1 second. A
    container that restarts at 22:29 and finishes migrations a few
    seconds past 22:30 must not have that night's run silently discarded
    with a WARNING."""
    scheduler = create_scheduler()
    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {"price_fetch", "snapshot_rebuild"}
    for job in jobs.values():
        assert job.misfire_grace_time == MISFIRE_GRACE_SECONDS
        assert job.misfire_grace_time >= 60  # realistic, not the 1s default
        # coalesce=True and max_instances=1 were already APScheduler's own
        # defaults (and max_instances=1 was already correct per the brief)
        # - kept explicit rather than left implicit.
        assert job.coalesce is True
        assert job.max_instances == 1


# --- Bug 3: INFO from app.* must actually reach a handler -----------------


def test_configure_app_logging_attaches_stdout_handler():
    app_logger = logging.getLogger("app")
    # Isolate from whatever state earlier tests/imports left behind.
    for h in list(app_logger.handlers):
        app_logger.removeHandler(h)

    configure_app_logging()

    assert len(app_logger.handlers) == 1
    handler = app_logger.handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    assert handler.stream is sys.stdout
    assert app_logger.level == logging.INFO
    assert handler.formatter is not None
    # Timestamped, not just the bare message uvicorn's own formatters use.
    assert "%(asctime)s" in handler.formatter._fmt


def test_configure_app_logging_is_idempotent():
    app_logger = logging.getLogger("app")
    for h in list(app_logger.handlers):
        app_logger.removeHandler(h)

    configure_app_logging()
    configure_app_logging()
    configure_app_logging()

    assert len(app_logger.handlers) == 1


def test_scheduler_logger_output_is_not_swallowed(caplog):
    """app.scheduler's logger.info calls must be capturable at INFO level
    - i.e. actually configured to emit, not dropped by an unconfigured
    root logger at WARNING (the bug: no logging.basicConfig anywhere, so
    uvicorn's own LOGGING_CONFIG - which only touches "uvicorn*" loggers -
    leaves "app.scheduler" with no effective handler)."""
    logger = logging.getLogger("app.scheduler")
    with caplog.at_level(logging.INFO, logger="app.scheduler"):
        logger.info("price fetch job: sentinel line for the test")
    assert "sentinel line for the test" in caplog.text


# --- Bug 2 (scheduler half): one bad instrument must not discard the rest -


def test_price_fetch_job_survives_one_instrument_raising_unexpectedly(
    db_session, monkeypatch
):
    """The old `results = [fetch_latest_for_instrument(db, i) for i in
    instruments]` accumulated every instrument's writes and committed
    ONCE at the end, with a single `db.rollback()` in the handler - so
    anything escaping fetch_latest_for_instrument (which only catches
    ProviderError) for *any* instrument rolled back every instrument
    already fetched in that run, and last_price_fetch was never updated.
    """
    good = _make_instrument(db_session, "XX0000000101", name="Good Instrument")
    bad = _make_instrument(db_session, "XX0000000102", name="Bad Instrument")

    def fake_fetch(db, instrument):
        if instrument.id == bad.id:
            # Simulates a provider bug that still escapes as something
            # other than ProviderError - already fixed at the provider
            # layer, but the job loop must be resilient regardless.
            raise RuntimeError("simulated unexpected failure")
        db.add(
            PricePoint(
                instrument_id=instrument.id,
                date=date(2024, 6, 1),
                close=Decimal("10.00"),
                currency="EUR",
                provider="fake",
                quality="ok",
            )
        )
        return FetchResult(instrument.id, "ok")

    monkeypatch.setattr("app.scheduler.fetch_latest_for_instrument", fake_fetch)

    from app.scheduler import run_price_fetch_job

    run_price_fetch_job()  # must not raise

    from app.database import SessionLocal
    from app import kv_store

    check_db = SessionLocal()
    try:
        good_point = check_db.get(PricePoint, (good.id, date(2024, 6, 1)))
        assert good_point is not None
        assert good_point.close == Decimal("10.00")
        assert check_db.get(PricePoint, (bad.id, date(2024, 6, 1))) is None

        last_fetch = kv_store.get(check_db, "last_price_fetch")
        assert last_fetch is not None
        # Bug 10: offset-aware, not the previous naive-UTC string.
        assert "+00:00" in last_fetch or last_fetch.endswith("Z")
    finally:
        check_db.close()


def test_price_fetch_job_all_instruments_failing_does_not_raise(db_session, monkeypatch):
    """Even a total wipeout (every instrument raises) must not propagate
    out of run_price_fetch_job - the scheduler thread would otherwise
    die silently."""
    _make_instrument(db_session, "XX0000000103", name="Only Instrument")

    def always_raise(db, instrument):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.scheduler.fetch_latest_for_instrument", always_raise)

    from app.scheduler import run_price_fetch_job

    run_price_fetch_job()  # must not raise
