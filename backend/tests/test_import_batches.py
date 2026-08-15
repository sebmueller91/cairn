def test_delete_batch_rolls_back_every_row_in_it(client, auth_headers):
    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Test ETF",
            "isin": "XX0000000020",
            "asset_class": "EQUITY",
            "valuation_mode": "MARKET",
            "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]

    result = client.post(
        "/api/transactions/bulk",
        json={
            "dry_run": False,
            "import_batch_label": "annual statement 2024",
            "transactions": [
                {
                    "external_id": "b-buy-1",
                    "date": "2024-01-10",
                    "type": "BUY",
                    "account_id": account,
                    "instrument_id": instrument,
                    "quantity": "5",
                    "price": "100.00",
                    "currency": "EUR",
                },
                {
                    "external_id": "b-buy-2",
                    "date": "2024-02-10",
                    "type": "BUY",
                    "account_id": account,
                    "instrument_id": instrument,
                    "quantity": "5",
                    "price": "110.00",
                    "currency": "EUR",
                },
            ],
        },
        headers=auth_headers,
    )
    batch_id = result.json()["import_batch_id"]
    assert batch_id is not None

    before = client.get(
        "/api/transactions", params={"account_id": account}, headers=auth_headers
    ).json()
    assert len(before) == 2

    rollback = client.delete(f"/api/import-batches/{batch_id}", headers=auth_headers)
    assert rollback.status_code == 204

    after = client.get(
        "/api/transactions", params={"account_id": account}, headers=auth_headers
    ).json()
    assert after == []


def test_delete_unknown_batch_404s(client, auth_headers):
    resp = client.delete("/api/import-batches/999999", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "import_batch_not_found"
