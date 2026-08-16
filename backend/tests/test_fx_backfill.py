"""FX history backfill (POST /api/prices/fx-backfill).

The bug this closes: a USD-priced instrument valued correctly today and at
EUR 0 for every historical date, because only the latest FX rate had ever
been fetched and the valuation path skips a position whose FX lookup
misses instead of raising.
"""

from datetime import date
from decimal import Decimal

from app.models import FxRate, Instrument
from app.price_fetch_service import backfill_all_fx_rates, backfill_fx_rate
from app.providers import registry
from app.providers.base import FetchedPrice


class _StubFrankfurter:
    name = "frankfurter"

    def __init__(self, rates):
        self.rates = rates
        self.calls = []

    def fetch_history(self, symbol, start, end):
        self.calls.append((symbol, start, end))
        return [FetchedPrice(date=d, close=c) for d, c in self.rates]


def _install(monkeypatch, stub):
    real = registry.get_provider

    def fake(name):
        return stub if name == "frankfurter" else real(name)

    monkeypatch.setattr("app.price_fetch_service.get_provider", fake)


def test_backfill_writes_one_row_per_day(db_session, monkeypatch):
    stub = _StubFrankfurter([
        (date(2025, 6, 2), Decimal("0.88")),
        (date(2025, 6, 3), Decimal("0.89")),
    ])
    _install(monkeypatch, stub)

    result = backfill_fx_rate(db_session, "USD", date(2025, 6, 1), date(2025, 6, 3))
    db_session.commit()

    assert result.status == "ok"
    assert "2 rates written" in result.detail
    assert db_session.get(FxRate, ("USD", date(2025, 6, 2))).eur_rate == Decimal("0.88")
    assert db_session.get(FxRate, ("USD", date(2025, 6, 3))).eur_rate == Decimal("0.89")


def test_backfill_is_idempotent_and_updates_in_place(db_session, monkeypatch):
    _install(monkeypatch, _StubFrankfurter([(date(2025, 6, 2), Decimal("0.88"))]))
    backfill_fx_rate(db_session, "USD", date(2025, 6, 1), date(2025, 6, 3))
    db_session.commit()

    # A corrected rate for a date already stored overwrites rather than
    # duplicating — (currency, date) is the primary key.
    _install(monkeypatch, _StubFrankfurter([(date(2025, 6, 2), Decimal("0.90"))]))
    result = backfill_fx_rate(db_session, "USD", date(2025, 6, 1), date(2025, 6, 3))
    db_session.commit()

    assert "0 rates written" in result.detail
    assert db_session.get(FxRate, ("USD", date(2025, 6, 2))).eur_rate == Decimal("0.90")
    assert db_session.query(FxRate).filter(FxRate.currency == "USD").count() == 1


def test_eur_is_a_noop(db_session, monkeypatch):
    _install(monkeypatch, _StubFrankfurter([]))
    result = backfill_fx_rate(db_session, "EUR", date(2025, 6, 1), date(2025, 6, 3))
    assert result.status == "ok"
    assert db_session.query(FxRate).count() == 0


def test_backfill_all_covers_every_non_eur_currency_in_use(db_session, monkeypatch):
    for currency in ("EUR", "USD", "CHF"):
        db_session.add(Instrument(
            name=f"test {currency}", asset_class="EQUITY", valuation_mode="MARKET",
            currency=currency,
        ))
    db_session.commit()

    stub = _StubFrankfurter([(date(2025, 6, 2), Decimal("0.88"))])
    _install(monkeypatch, stub)
    results = backfill_all_fx_rates(db_session, date(2025, 6, 1), date(2025, 6, 3))
    db_session.commit()

    assert [c[0] for c in stub.calls] == ["CHF", "USD"]  # sorted, EUR skipped
    assert all(r.status == "ok" for r in results)


def test_endpoint_returns_per_currency_results(client, auth_headers, db_session, monkeypatch):
    db_session.add(Instrument(
        name="usd thing", asset_class="COMMODITY", valuation_mode="MARKET", currency="USD",
    ))
    db_session.commit()
    _install(monkeypatch, _StubFrankfurter([(date(2025, 6, 2), Decimal("0.88"))]))

    response = client.post("/api/prices/fx-backfill",
                           json={"start": "2025-06-01", "end": "2025-06-03"},
                           headers=auth_headers)

    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["status"] == "ok"
    assert "USD" in results[0]["detail"]
