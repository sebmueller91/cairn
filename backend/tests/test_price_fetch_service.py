"""Fetch job logic tested against a fake provider — no real network here,
that's verified separately against the live deployment."""

from datetime import date
from decimal import Decimal

import pytest

from app.models import AssetClass, FxRate, Instrument, PriceSource, ValuationMode
from app.price_fetch_service import (
    backfill_for_instrument,
    fetch_all_fx_rates,
    fetch_latest_for_instrument,
)
from app.providers.base import FetchedPrice, ProviderError


class FakeProvider:
    def __init__(self, latest=None, history=None, raise_error=False):
        self._latest = latest
        self._history = history or []
        self._raise_error = raise_error

    def fetch_latest(self, symbol):
        if self._raise_error:
            raise ProviderError("boom")
        return self._latest

    def fetch_history(self, symbol, start, end):
        if self._raise_error:
            raise ProviderError("boom")
        return self._history


@pytest.fixture
def instrument(db_session):
    i = Instrument(
        name="Test ETF",
        isin="XX0000000070",
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


def test_fetch_latest_with_no_sources_configured(db_session, instrument):
    result = fetch_latest_for_instrument(db_session, instrument)
    assert result.status == "no_sources"


def test_fetch_latest_falls_through_to_second_source(db_session, instrument, monkeypatch):
    source_a = PriceSource(
        instrument_id=instrument.id, provider="stooq", provider_symbol="X", priority=0
    )
    source_b = PriceSource(
        instrument_id=instrument.id, provider="coingecko", provider_symbol="Y", priority=1
    )
    db_session.add_all([source_a, source_b])
    db_session.commit()

    providers = {
        "stooq": FakeProvider(raise_error=True),
        "coingecko": FakeProvider(latest=FetchedPrice(date=date(2024, 6, 1), close=Decimal("100.00"))),
    }
    monkeypatch.setattr(
        "app.price_fetch_service.get_provider", lambda name: providers[name]
    )

    result = fetch_latest_for_instrument(db_session, instrument)
    assert result.status == "ok"
    assert source_a.last_error == "boom"
    assert source_b.last_error is None


def test_implausible_price_is_not_adopted(db_session, instrument, monkeypatch):
    from app.models import PricePoint

    db_session.add(
        PricePoint(
            instrument_id=instrument.id,
            date=date(2024, 5, 31),
            close=Decimal("100.00"),
            currency="EUR",
            provider="stooq",
            quality="ok",
        )
    )
    source = PriceSource(
        instrument_id=instrument.id, provider="stooq", provider_symbol="X", priority=0
    )
    db_session.add(source)
    db_session.commit()

    # 200.00 is a >25% jump from the last known 100.00 -> should be rejected
    monkeypatch.setattr(
        "app.price_fetch_service.get_provider",
        lambda name: FakeProvider(
            latest=FetchedPrice(date=date(2024, 6, 1), close=Decimal("200.00"))
        ),
    )

    result = fetch_latest_for_instrument(db_session, instrument)
    assert result.status == "all_sources_failed"
    assert "not adopted" in source.last_error


def test_backfill_writes_history_and_skips_implausible_points(
    db_session, instrument, monkeypatch
):
    history = [
        FetchedPrice(date=date(2024, 1, 1), close=Decimal("100.00")),
        FetchedPrice(date=date(2024, 1, 2), close=Decimal("500.00")),  # implausible, skipped
        FetchedPrice(date=date(2024, 1, 3), close=Decimal("101.00")),
    ]
    source = PriceSource(
        instrument_id=instrument.id, provider="stooq", provider_symbol="X", priority=0
    )
    db_session.add(source)
    db_session.commit()

    monkeypatch.setattr(
        "app.price_fetch_service.get_provider",
        lambda name: FakeProvider(history=history),
    )

    result = backfill_for_instrument(db_session, instrument, date(2024, 1, 1), date(2024, 1, 3))
    assert result.status == "ok"
    assert "2 points written" in result.detail


def _make_instrument(db_session, isin, currency):
    i = Instrument(
        name="Test Instrument",
        isin=isin,
        asset_class=AssetClass.EQUITY,
        valuation_mode=ValuationMode.MARKET,
        currency=currency,
        valuation_config_json="{}",
        tags_json="[]",
    )
    db_session.add(i)
    db_session.commit()
    db_session.refresh(i)
    return i


def test_fetch_all_fx_rates_fetches_distinct_non_eur_currencies(db_session, monkeypatch):
    # Two USD instruments and one EUR instrument -> only one USD fetch,
    # no EUR fetch (spec: EUR is always 1:1, never an FX row).
    _make_instrument(db_session, "XX0000000081", "USD")
    _make_instrument(db_session, "XX0000000082", "USD")
    _make_instrument(db_session, "XX0000000083", "EUR")

    calls = []

    class FakeProvider:
        def fetch_latest(self, symbol):
            calls.append(symbol)
            return FetchedPrice(date=date(2024, 6, 1), close=Decimal("1.10"))

    monkeypatch.setattr(
        "app.price_fetch_service.get_provider", lambda name: FakeProvider()
    )

    results = fetch_all_fx_rates(db_session)
    db_session.commit()

    assert calls == ["USD"]
    assert [r.status for r in results] == ["ok"]

    rate = db_session.get(FxRate, ("USD", date(2024, 6, 1)))
    assert rate is not None
    assert rate.eur_rate == Decimal("1.10")


def test_fetch_all_fx_rates_is_noop_for_eur_only_portfolio(db_session, monkeypatch):
    _make_instrument(db_session, "XX0000000084", "EUR")

    def _unexpected_provider(name):
        raise AssertionError("no provider should be looked up for an EUR-only portfolio")

    monkeypatch.setattr("app.price_fetch_service.get_provider", _unexpected_provider)

    results = fetch_all_fx_rates(db_session)

    assert results == []
