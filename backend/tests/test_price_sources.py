def _create_instrument(client, headers):
    r = client.post(
        "/api/instruments",
        json={
            "name": "Test ETF",
            "isin": "XX0000000060",
            "ticker": "EUNL.DE",
            "asset_class": "EQUITY",
            "valuation_mode": "MARKET",
            "currency": "EUR",
        },
        headers=headers,
    )
    return r.json()["id"]


def test_create_and_list_price_sources(client, auth_headers):
    instrument_id = _create_instrument(client, auth_headers)

    create = client.post(
        f"/api/instruments/{instrument_id}/price-sources",
        json={"provider": "stooq", "provider_symbol": "EUNL.DE", "priority": 0},
        headers=auth_headers,
    )
    assert create.status_code == 201
    assert create.json()["enabled"] is True

    listed = client.get(
        f"/api/instruments/{instrument_id}/price-sources", headers=auth_headers
    )
    assert len(listed.json()) == 1


def test_unknown_provider_rejected(client, auth_headers):
    instrument_id = _create_instrument(client, auth_headers)
    resp = client.post(
        f"/api/instruments/{instrument_id}/price-sources",
        json={"provider": "yahoo-unofficial", "provider_symbol": "EUNL.DE"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "unknown_price_provider"


def test_disable_and_delete_price_source(client, auth_headers):
    instrument_id = _create_instrument(client, auth_headers)
    source = client.post(
        f"/api/instruments/{instrument_id}/price-sources",
        json={"provider": "stooq", "provider_symbol": "EUNL.DE"},
        headers=auth_headers,
    ).json()

    disabled = client.patch(
        f"/api/instruments/{instrument_id}/price-sources/{source['id']}",
        json={"enabled": False},
        headers=auth_headers,
    )
    assert disabled.json()["enabled"] is False

    deleted = client.delete(
        f"/api/instruments/{instrument_id}/price-sources/{source['id']}",
        headers=auth_headers,
    )
    assert deleted.status_code == 204
