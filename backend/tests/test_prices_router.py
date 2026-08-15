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
