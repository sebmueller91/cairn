"""The price fetch job (spec 5): per instrument, try price_source rows in
priority order until one returns a plausible value. Never called from the
UI request path — only the scheduler and the manual refresh/backfill
endpoints call this.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import FxRate, Instrument, PricePoint, PriceSource
from app.providers.base import ProviderError
from app.providers.registry import get_provider

PLAUSIBILITY_MAX_DAILY_MOVE = Decimal("0.25")


def _is_plausible(new_price: Decimal, previous: Decimal | None) -> bool:
    if new_price <= 0:
        return False
    if previous is None or previous == 0:
        return True
    change = abs(new_price - previous) / previous
    return change <= PLAUSIBILITY_MAX_DAILY_MOVE


def _latest_close(db: Session, instrument_id: int) -> Decimal | None:
    row = (
        db.query(PricePoint)
        .filter(PricePoint.instrument_id == instrument_id)
        .order_by(PricePoint.date.desc())
        .first()
    )
    return row.close if row else None


def _upsert_price_point(
    db: Session,
    instrument_id: int,
    point_date: date,
    close: Decimal,
    currency: str,
    provider: str,
    quality: str = "ok",
) -> None:
    existing = db.get(PricePoint, (instrument_id, point_date))
    if existing:
        existing.close = close
        existing.currency = currency
        existing.provider = provider
        existing.quality = quality
        existing.fetched_at = datetime.now(UTC).replace(tzinfo=None)
    else:
        db.add(
            PricePoint(
                instrument_id=instrument_id,
                date=point_date,
                close=close,
                currency=currency,
                provider=provider,
                quality=quality,
            )
        )


@dataclass
class FetchResult:
    instrument_id: int
    status: str  # ok | no_sources | all_sources_failed
    detail: str | None = None


def fetch_latest_for_instrument(db: Session, instrument: Instrument) -> FetchResult:
    sources = (
        db.query(PriceSource)
        .filter(PriceSource.instrument_id == instrument.id, PriceSource.enabled.is_(True))
        .order_by(PriceSource.priority)
        .all()
    )
    if not sources:
        return FetchResult(instrument.id, "no_sources")

    previous = _latest_close(db, instrument.id)
    now = datetime.now(UTC).replace(tzinfo=None)

    for source in sources:
        provider = get_provider(source.provider)
        try:
            result = provider.fetch_latest(source.provider_symbol)
        except ProviderError as e:
            source.last_error = str(e)
            continue
        if result is None:
            source.last_error = "no data returned"
            continue
        if not _is_plausible(result.close, previous):
            # Rule 3 (spec 5): a >25% move or a zero price is suspect and
            # is not adopted — try the next source rather than trust it.
            source.last_error = (
                f"suspect price {result.close} vs previous {previous}, not adopted"
            )
            continue

        _upsert_price_point(
            db, instrument.id, result.date, result.close, instrument.currency, source.provider
        )
        source.last_fetch_at = now
        source.last_error = None
        return FetchResult(instrument.id, "ok")

    return FetchResult(instrument.id, "all_sources_failed")


def backfill_for_instrument(
    db: Session, instrument: Instrument, start: date, end: date
) -> FetchResult:
    sources = (
        db.query(PriceSource)
        .filter(PriceSource.instrument_id == instrument.id, PriceSource.enabled.is_(True))
        .order_by(PriceSource.priority)
        .all()
    )
    if not sources:
        return FetchResult(instrument.id, "no_sources")

    for source in sources:
        provider = get_provider(source.provider)
        try:
            points = provider.fetch_history(source.provider_symbol, start, end)
        except ProviderError as e:
            source.last_error = str(e)
            continue
        if not points:
            source.last_error = "no history returned"
            continue

        written = 0
        prev_close: Decimal | None = None
        for point in points:
            if _is_plausible(point.close, prev_close):
                _upsert_price_point(
                    db, instrument.id, point.date, point.close, instrument.currency, source.provider
                )
                written += 1
                prev_close = point.close
            # An implausible point is simply skipped, not persisted as
            # 'suspect' — same "not adopted" rule as the live refresh
            # (spec 5 rule 3), applied uniformly for now.
        source.last_fetch_at = datetime.now(UTC).replace(tzinfo=None)
        source.last_error = None
        return FetchResult(instrument.id, "ok", detail=f"{written} points written")

    return FetchResult(instrument.id, "all_sources_failed")


def fetch_fx_rate(db: Session, currency: str) -> FetchResult:
    # instrument_id=0 is a sentinel: FX rows aren't tied to a single
    # instrument. `detail` carries the currency so callers (and the
    # /api/prices/refresh response, which reuses FetchResultRead as-is)
    # can tell which currency a given FX result is about.
    if currency == "EUR":
        return FetchResult(0, "ok", detail="EUR is always 1:1")
    provider = get_provider("frankfurter")
    try:
        result = provider.fetch_latest(currency)
    except ProviderError as e:
        return FetchResult(0, "all_sources_failed", detail=f"{currency}: {e}")
    if result is None:
        return FetchResult(0, "all_sources_failed", detail=f"{currency}: no data")

    existing = db.get(FxRate, (currency, result.date))
    if existing:
        existing.eur_rate = result.close
    else:
        db.add(FxRate(currency=currency, date=result.date, eur_rate=result.close))
    return FetchResult(0, "ok", detail=currency)


def backfill_fx_rate(db: Session, currency: str, start: date, end: date) -> FetchResult:
    """History counterpart to fetch_fx_rate. Without this, a non-EUR
    instrument values correctly today and as EUR 0 for every date before
    the first nightly FX fetch — silently, because the valuation path
    skips a position whose FX lookup misses rather than failing loudly.
    Same instrument_id=0 sentinel and `detail`-carries-the-currency
    convention as fetch_fx_rate.
    """
    if currency == "EUR":
        return FetchResult(0, "ok", detail="EUR is always 1:1")
    provider = get_provider("frankfurter")
    try:
        results = provider.fetch_history(currency, start, end)
    except ProviderError as e:
        return FetchResult(0, "all_sources_failed", detail=f"{currency}: {e}")
    if not results:
        return FetchResult(0, "all_sources_failed", detail=f"{currency}: no data")

    written = 0
    for result in results:
        existing = db.get(FxRate, (currency, result.date))
        if existing:
            existing.eur_rate = result.close
        else:
            db.add(FxRate(currency=currency, date=result.date, eur_rate=result.close))
            written += 1
    return FetchResult(0, "ok", detail=f"{currency}: {written} rates written")


def backfill_all_fx_rates(db: Session, start: date, end: date) -> list[FetchResult]:
    """Every non-EUR currency in use, mirroring fetch_all_fx_rates."""
    currencies = {
        currency
        for (currency,) in db.query(Instrument.currency).distinct().all()
        if currency != "EUR"
    }
    return [backfill_fx_rate(db, currency, start, end) for currency in sorted(currencies)]


def fetch_all_fx_rates(db: Session) -> list[FetchResult]:
    """Fetch one FX rate per distinct non-EUR currency in use across all
    instruments. This is what actually populates `fx_rate` — without it,
    fetch_fx_rate is defined but never invoked, and the snapshot/valuation
    engines silently treat any non-EUR position as worth EUR 0 (fx_series
    lookup misses -> `if fx is None: continue`).
    """
    currencies = {
        currency
        for (currency,) in db.query(Instrument.currency).distinct().all()
        if currency != "EUR"
    }
    return [fetch_fx_rate(db, currency) for currency in sorted(currencies)]
