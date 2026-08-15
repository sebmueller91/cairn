def test_create_anchor_for_anchored_instrument(client, auth_headers):
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

    resp = client.post(
        "/api/valuations",
        json={
            "instrument_id": house["id"],
            "date": "2020-01-01",
            "value_eur": "400000.00",
            "method": "purchase",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["method"] == "purchase"

    listed = client.get(
        "/api/valuations", params={"instrument_id": house["id"]}, headers=auth_headers
    )
    assert len(listed.json()) == 1


def test_anchor_rejected_for_market_instrument(client, auth_headers):
    etf = client.post(
        "/api/instruments",
        json={
            "name": "Test ETF",
            "isin": "XX0000001000",
            "asset_class": "EQUITY",
            "valuation_mode": "MARKET",
            "currency": "EUR",
        },
        headers=auth_headers,
    ).json()

    resp = client.post(
        "/api/valuations",
        json={"instrument_id": etf["id"], "date": "2024-01-01", "value_eur": "100.00"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "valuation_mode_has_no_anchors"
