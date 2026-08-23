"""API-level validation gaps in POST /api/transactions (AGENTS.md: never
put real amounts/ISINs in tests — invented numbers only).

Covers:
- bug 4: split_ratio<=0 currently books a 201 that then DivisionByZeros
  every /api/positions and /api/tax read forever.
- bug 5: negative quantities on BUY/SELL/TRANSFER currently book a 201
  and push a negative lot into the FIFO queue.
- bug 9: GET /api/transactions?limit has no floor, so limit=-1 means
  "unlimited" on SQLite.
"""


def _create_account(client, headers, name="Portfolio A", type_="BROKERAGE"):
    r = client.post(
        "/api/accounts",
        json={"name": name, "type": type_, "currency": "EUR"},
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()["id"]


def _create_instrument(client, headers, name="Test World ETF", isin="XX0000000030"):
    r = client.post(
        "/api/instruments",
        json={
            "name": name,
            "isin": isin,
            "asset_class": "EQUITY",
            "valuation_mode": "MARKET",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()["id"]


def test_zero_split_ratio_is_rejected(client, auth_headers):
    account_id = _create_account(client, auth_headers)
    instrument_id = _create_instrument(client, auth_headers)

    resp = client.post(
        "/api/transactions",
        json={
            "external_id": "split-zero",
            "date": "2024-01-10",
            "type": "SPLIT",
            "account_id": account_id,
            "instrument_id": instrument_id,
            "split_ratio": "0",
            "currency": "EUR",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "invalid_split_ratio"

    # Nothing was booked — a subsequent /positions read must not 500.
    positions = client.get("/api/positions", headers=auth_headers)
    assert positions.status_code == 200


def test_negative_split_ratio_is_rejected(client, auth_headers):
    account_id = _create_account(client, auth_headers)
    instrument_id = _create_instrument(client, auth_headers)

    resp = client.post(
        "/api/transactions",
        json={
            "external_id": "split-negative",
            "date": "2024-01-10",
            "type": "SPLIT",
            "account_id": account_id,
            "instrument_id": instrument_id,
            "split_ratio": "-2",
            "currency": "EUR",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "invalid_split_ratio"


def test_negative_buy_quantity_is_rejected(client, auth_headers):
    account_id = _create_account(client, auth_headers)
    instrument_id = _create_instrument(client, auth_headers)

    resp = client.post(
        "/api/transactions",
        json={
            "external_id": "buy-negative-qty",
            "date": "2024-01-10",
            "type": "BUY",
            "account_id": account_id,
            "instrument_id": instrument_id,
            "quantity": "-5",
            "price": "100.00",
            "currency": "EUR",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "invalid_quantity"

    listed = client.get(
        "/api/transactions", params={"account_id": account_id}, headers=auth_headers
    )
    assert listed.json() == []


def test_zero_sell_quantity_is_rejected(client, auth_headers):
    account_id = _create_account(client, auth_headers)
    instrument_id = _create_instrument(client, auth_headers)

    resp = client.post(
        "/api/transactions",
        json={
            "external_id": "sell-zero-qty",
            "date": "2024-01-10",
            "type": "SELL",
            "account_id": account_id,
            "instrument_id": instrument_id,
            "quantity": "0",
            "price": "100.00",
            "currency": "EUR",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "invalid_quantity"


def test_negative_transfer_quantity_is_rejected(client, auth_headers):
    account_id = _create_account(client, auth_headers, name="Source")
    dest_id = _create_account(client, auth_headers, name="Dest")
    instrument_id = _create_instrument(client, auth_headers)

    resp = client.post(
        "/api/transactions",
        json={
            "external_id": "transfer-negative-qty",
            "date": "2024-01-10",
            "type": "TRANSFER",
            "account_id": account_id,
            "counter_account_id": dest_id,
            "instrument_id": instrument_id,
            "quantity": "-3",
            "currency": "EUR",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "invalid_quantity"


def test_transactions_limit_rejects_negative_value(client, auth_headers):
    resp = client.get("/api/transactions", params={"limit": -1}, headers=auth_headers)
    assert resp.status_code == 422


def test_transactions_limit_rejects_absurdly_large_value(client, auth_headers):
    resp = client.get(
        "/api/transactions", params={"limit": 1_000_000}, headers=auth_headers
    )
    assert resp.status_code == 422
