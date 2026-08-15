"""spec 2.5, mechanism 2: backfilling history behind a provisional opening
balance must never double-count and must flag what it can't explain."""


def _setup_account_and_instrument(client, headers):
    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=headers,
    ).json()["id"]
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Test ETF",
            "isin": "XX0000000030",
            "asset_class": "EQUITY",
            "valuation_mode": "MARKET",
            "currency": "EUR",
        },
        headers=headers,
    ).json()["id"]
    return account, instrument


def _book_opening_balance(client, headers, account, instrument, quantity, amount_eur):
    resp = client.post(
        "/api/transactions",
        json={
            "external_id": f"ob-{account}-{instrument}",
            "date": "2024-06-01",
            "type": "OPENING_BALANCE",
            "account_id": account,
            "instrument_id": instrument,
            "quantity": quantity,
            "amount": amount_eur,
            "currency": "EUR",
            "provisional": True,
        },
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def test_supersede_matching_backfill_voids_opening_balance(client, auth_headers):
    account, instrument = _setup_account_and_instrument(client, auth_headers)
    ob_id = _book_opening_balance(client, auth_headers, account, instrument, "10", "1000.00")

    backfill = client.post(
        "/api/transactions/bulk",
        json={
            "dry_run": False,
            "import_batch_label": "backfilled 2023-2024",
            "transactions": [
                {
                    "external_id": "backfill-buy-1",
                    "date": "2024-01-01",
                    "type": "BUY",
                    "account_id": account,
                    "instrument_id": instrument,
                    "quantity": "10",
                    "price": "100.00",
                    "currency": "EUR",
                }
            ],
        },
        headers=auth_headers,
    )
    batch_id = backfill.json()["import_batch_id"]

    supersede = client.post(
        f"/api/import-batches/{batch_id}/supersede", json={}, headers=auth_headers
    )
    assert supersede.status_code == 200
    reports = supersede.json()["reports"]
    assert len(reports) == 1
    assert reports[0]["opening_balance_txn_id"] == ob_id
    assert reports[0]["matched"] is True
    assert reports[0]["residual_txn_id"] is None

    # opening balance is voided -> excluded from the active list
    active = client.get(
        "/api/transactions", params={"account_id": account}, headers=auth_headers
    ).json()
    assert ob_id not in [t["id"] for t in active]

    # no double counting: just the backfilled 10 units, not 20
    positions = client.get(
        "/api/positions", params={"account_id": account}, headers=auth_headers
    ).json()
    assert positions[0]["quantity"] == "10"
    assert positions[0]["cost_basis_eur"] == "1000.00"


def test_supersede_mismatch_leaves_flagged_residual(client, auth_headers):
    account, instrument = _setup_account_and_instrument(client, auth_headers)
    ob_id = _book_opening_balance(client, auth_headers, account, instrument, "10", "1000.00")

    # only 8 of the 10 units are explained by the backfilled history
    backfill = client.post(
        "/api/transactions/bulk",
        json={
            "dry_run": False,
            "transactions": [
                {
                    "external_id": "backfill-buy-partial",
                    "date": "2024-01-01",
                    "type": "BUY",
                    "account_id": account,
                    "instrument_id": instrument,
                    "quantity": "8",
                    "price": "100.00",
                    "currency": "EUR",
                }
            ],
        },
        headers=auth_headers,
    )
    batch_id = backfill.json()["import_batch_id"]

    supersede = client.post(
        f"/api/import-batches/{batch_id}/supersede", json={}, headers=auth_headers
    )
    reports = supersede.json()["reports"]
    assert reports[0]["opening_balance_txn_id"] == ob_id
    assert reports[0]["matched"] is False
    residual_id = reports[0]["residual_txn_id"]
    assert residual_id is not None

    # total wealth is preserved exactly: 8 explained + 2 residual = 10
    positions = client.get(
        "/api/positions", params={"account_id": account}, headers=auth_headers
    ).json()
    assert positions[0]["quantity"] == "10"
    assert positions[0]["cost_basis_eur"] == "1000.00"

    residual = client.get(
        "/api/transactions", params={"account_id": account}, headers=auth_headers
    ).json()
    residual_txn = next(t for t in residual if t["id"] == residual_id)
    assert residual_txn["quantity"] == "2"
    assert residual_txn["amount_eur"] == "200.00"
    assert residual_txn["provisional"] is True
