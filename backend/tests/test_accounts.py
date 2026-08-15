SAMPLE_ACCOUNT = {
    "name": "Test Brokerage",
    "type": "BROKERAGE",
    "currency": "EUR",
}


def test_create_requires_auth(client):
    response = client.post("/api/accounts", json=SAMPLE_ACCOUNT)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "unauthorized"


def test_create_rejects_readonly_token(client, readonly_headers):
    response = client.post(
        "/api/accounts", json=SAMPLE_ACCOUNT, headers=readonly_headers
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "read_only_token"


def test_readonly_token_can_list(client, readonly_headers):
    response = client.get("/api/accounts", headers=readonly_headers)
    assert response.status_code == 200


def test_crud_round_trip(client, auth_headers):
    create = client.post("/api/accounts", json=SAMPLE_ACCOUNT, headers=auth_headers)
    assert create.status_code == 201
    account = create.json()
    assert account["name"] == "Test Brokerage"
    assert account["archived"] is False
    account_id = account["id"]

    listed = client.get("/api/accounts", headers=auth_headers)
    assert listed.status_code == 200
    assert any(a["id"] == account_id for a in listed.json())

    fetched = client.get(f"/api/accounts/{account_id}", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == account_id

    updated = client.patch(
        f"/api/accounts/{account_id}",
        json={"archived": True},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["archived"] is True

    deleted = client.delete(f"/api/accounts/{account_id}", headers=auth_headers)
    assert deleted.status_code == 204

    missing = client.get(f"/api/accounts/{account_id}", headers=auth_headers)
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "account_not_found"


def test_session_cookie_auth(client):
    login = client.post("/api/auth/session", json={"token": "test-token"})
    assert login.status_code == 200
    assert login.json()["scope"] == "full"

    create = client.post("/api/accounts", json=SAMPLE_ACCOUNT)
    assert create.status_code == 201


def test_session_cookie_rejects_invalid_token(client):
    login = client.post("/api/auth/session", json={"token": "wrong"})
    assert login.status_code == 401


def test_delete_rejects_account_with_transactions(client, auth_headers):
    account = client.post(
        "/api/accounts", json=SAMPLE_ACCOUNT, headers=auth_headers
    ).json()
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Test ETF",
            "isin": "XX0000000040",
            "asset_class": "EQUITY",
            "valuation_mode": "MARKET",
            "currency": "EUR",
        },
        headers=auth_headers,
    ).json()
    client.post(
        "/api/transactions",
        json={
            "external_id": "acct-delete-guard",
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

    resp = client.delete(f"/api/accounts/{account['id']}", headers=auth_headers)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "account_has_transactions"
