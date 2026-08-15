from datetime import date
from decimal import Decimal

from app.providers.base import FetchedPrice


def _create_instrument_with_source(client, headers):
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Test ETF",
            "isin": "XX0000000080",
            "asset_class": "EQUITY",
            "valuation_mode": "MARKET",
            "currency": "EUR",
        },
        headers=headers,
    ).json()
    client.post(
        f"/api/instruments/{instrument['id']}/price-sources",
        json={"provider": "stooq", "provider_symbol": "TEST.DE", "priority": 0},
        headers=headers,
    )
    return instrument["id"]


def test_refresh_unknown_instrument_404s(client, auth_headers):
    resp = client.post(
        "/api/prices/refresh", json={"instrument_id": 999999}, headers=auth_headers
    )
    assert resp.status_code == 404


def test_refresh_uses_provider_and_writes_price_point(client, auth_headers, monkeypatch):
    instrument_id = _create_instrument_with_source(client, auth_headers)

    class FakeProvider:
        def fetch_latest(self, symbol):
            return FetchedPrice(date=date(2024, 6, 1), close=Decimal("42.50"))

    monkeypatch.setattr(
        "app.price_fetch_service.get_provider", lambda name: FakeProvider()
    )

    resp = client.post(
        "/api/prices/refresh", json={"instrument_id": instrument_id}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["results"][0]["status"] == "ok"

    health = client.get("/api/health").json()
    assert health["last_price_fetch"] is not None


def test_refresh_all_also_fetches_fx_rates_for_non_eur_instruments(
    client, auth_headers, monkeypatch
):
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Test US ETF",
            "isin": "XX0000000090",
            "asset_class": "EQUITY",
            "valuation_mode": "MARKET",
            "currency": "USD",
        },
        headers=auth_headers,
    ).json()
    client.post(
        f"/api/instruments/{instrument['id']}/price-sources",
        json={"provider": "stooq", "provider_symbol": "TEST", "priority": 0},
        headers=auth_headers,
    )

    class FakeProvider:
        def fetch_latest(self, symbol):
            return FetchedPrice(date=date(2024, 6, 1), close=Decimal("1.10"))

    monkeypatch.setattr(
        "app.price_fetch_service.get_provider", lambda name: FakeProvider()
    )

    resp = client.post("/api/prices/refresh", json={}, headers=auth_headers)
    assert resp.status_code == 200
    results = resp.json()["results"]

    # One result for the instrument's own price point, one for the USD FX
    # rate (instrument_id 0 is the sentinel fetch_fx_rate already uses for
    # rows that aren't tied to a single instrument).
    assert any(r["status"] == "ok" and r["instrument_id"] == instrument["id"] for r in results)
    fx_results = [r for r in results if r["instrument_id"] == 0]
    assert len(fx_results) == 1
    assert fx_results[0]["status"] == "ok"
    assert "USD" in fx_results[0]["detail"]
