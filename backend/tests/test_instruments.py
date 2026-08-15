SAMPLE_INSTRUMENT = {
    "name": "Test World ETF",
    "isin": "XX0000000001",
    "ticker": "TEST.DE",
    "asset_class": "EQUITY",
    "valuation_mode": "MARKET",
    "currency": "EUR",
}


def test_create_requires_auth(client):
    response = client.post("/api/instruments", json=SAMPLE_INSTRUMENT)
    assert response.status_code == 401


def test_crud_round_trip(client, auth_headers):
    create = client.post(
        "/api/instruments", json=SAMPLE_INSTRUMENT, headers=auth_headers
    )
    assert create.status_code == 201
    instrument = create.json()
    assert instrument["name"] == "Test World ETF"
    assert instrument["valuation_config"] == {}
    assert instrument["tags"] == []
    instrument_id = instrument["id"]

    searched = client.get(
        "/api/instruments", params={"search": "Test World"}, headers=auth_headers
    )
    assert searched.status_code == 200
    assert any(i["id"] == instrument_id for i in searched.json())

    updated = client.patch(
        f"/api/instruments/{instrument_id}",
        json={"tags": ["core", "developed-markets"]},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["tags"] == ["core", "developed-markets"]

    deleted = client.delete(
        f"/api/instruments/{instrument_id}", headers=auth_headers
    )
    assert deleted.status_code == 204

    missing = client.get(f"/api/instruments/{instrument_id}", headers=auth_headers)
    assert missing.status_code == 404


def test_decimal_fields_are_exact(client, auth_headers):
    payload = {
        **SAMPLE_INSTRUMENT,
        "name": "Test Gold Coin",
        "isin": None,
        "asset_class": "COMMODITY",
        "fine_weight_g": "31.1035",
        "ter_pct": "0.00",
    }
    create = client.post("/api/instruments", json=payload, headers=auth_headers)
    assert create.status_code == 201
    body = create.json()
    # Serialized as a string, not a bare JSON number — see schemas.DecimalStr.
    # Quantity preserves exactly what was given, no padding/rounding.
    assert body["fine_weight_g"] == "31.1035"
    assert body["ter_pct"] == "0.00"


def test_delete_rejects_instrument_with_transactions(client, auth_headers):
    account = client.post(
        "/api/accounts",
        json={"name": "Test Brokerage", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()
    instrument = client.post(
        "/api/instruments",
        json={**SAMPLE_INSTRUMENT, "name": "Test Delete Guard", "isin": "XX0000000050"},
        headers=auth_headers,
    ).json()
    client.post(
        "/api/transactions",
        json={
            "external_id": "instr-delete-guard",
            "date": "2024-01-10",
            "type": "BUY",
            "account_id": account["id"],
            "instrument_id": instrument["id"],
            "quantity": "1",
            "price": "10.00",
            "currency": "EUR",
        },
        headers=auth_headers,
    )

    resp = client.delete(f"/api/instruments/{instrument['id']}", headers=auth_headers)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "instrument_has_transactions"


def test_delete_cascades_price_sources_and_price_points(client, auth_headers, db_session):
    from datetime import date
    from decimal import Decimal

    from app.models import PricePoint

    instrument = client.post(
        "/api/instruments",
        json={**SAMPLE_INSTRUMENT, "name": "Test Cascade", "isin": "XX0000000051"},
        headers=auth_headers,
    ).json()
    client.post(
        f"/api/instruments/{instrument['id']}/price-sources",
        json={"provider": "stooq", "provider_symbol": "TEST.DE"},
        headers=auth_headers,
    )
    db_session.add(
        PricePoint(
            instrument_id=instrument["id"],
            date=date(2024, 1, 1),
            close=Decimal("10.00"),
            currency="EUR",
            provider="stooq",
            quality="ok",
        )
    )
    db_session.commit()

    resp = client.delete(f"/api/instruments/{instrument['id']}", headers=auth_headers)
    assert resp.status_code == 204


def test_delete_cascades_valuation_anchors(client, auth_headers):
    house = client.post(
        "/api/instruments",
        json={
            "name": "Test House",
            "asset_class": "REAL_ESTATE",
            "valuation_mode": "ANCHORED",
            "currency": "EUR",
        },
        headers=auth_headers,
    ).json()
    client.post(
        "/api/valuations",
        json={
            "instrument_id": house["id"],
            "date": "2024-01-01",
            "value_eur": "400000.00",
            "method": "purchase",
        },
        headers=auth_headers,
    )

    resp = client.delete(f"/api/instruments/{house['id']}", headers=auth_headers)
    assert resp.status_code == 204


def test_valuation_config_for_modeled_instrument(client, auth_headers):
    payload = {
        **SAMPLE_INSTRUMENT,
        "name": "Test Car",
        "isin": None,
        "asset_class": "VEHICLE",
        "valuation_mode": "MODELED",
        "valuation_config": {
            "purchase_price_eur": "20000.00",
            "purchase_date": "2024-01-01",
            "first_registration": "2024-01-01",
            "mileage_at_purchase_km": 0,
            "annual_mileage_estimate_km": 12000,
        },
    }
    create = client.post("/api/instruments", json=payload, headers=auth_headers)
    assert create.status_code == 201
    assert create.json()["valuation_config"]["annual_mileage_estimate_km"] == 12000
