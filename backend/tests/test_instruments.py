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
