"""API-level tests for PATCH/DELETE /api/transactions and
DELETE /api/import-batches/{id} (AGENTS.md: invented numbers only).

Covers:
- bug 1: PATCH never recomputed amount_eur (the only field the ledger
  reads for cost) and never revalidated (e.g. bypassed the future-date
  check).
- bug 2: PATCH/DELETE could leave the ledger unreplayable — a later SELL
  starved by an edited/deleted BUY used to 500 every read endpoint
  forever instead of being rejected up front.
- bug 3: the same hole in DELETE /api/import-batches/{id}, where SELLs in
  a *different* batch can depend on the batch being rolled back.
"""


def _create_account(client, headers, name="Portfolio A", type_="BROKERAGE"):
    r = client.post(
        "/api/accounts",
        json={"name": name, "type": type_, "currency": "EUR"},
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()["id"]


def _create_instrument(client, headers, name="Test World ETF", isin="XX0000000040"):
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


def _buy(client, headers, account_id, instrument_id, external_id, date, qty, price):
    r = client.post(
        "/api/transactions",
        json={
            "external_id": external_id,
            "date": date,
            "type": "BUY",
            "account_id": account_id,
            "instrument_id": instrument_id,
            "quantity": qty,
            "price": price,
            "currency": "EUR",
        },
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()


def _sell(client, headers, account_id, instrument_id, external_id, date, qty, price):
    r = client.post(
        "/api/transactions",
        json={
            "external_id": external_id,
            "date": date,
            "type": "SELL",
            "account_id": account_id,
            "instrument_id": instrument_id,
            "quantity": qty,
            "price": price,
            "currency": "EUR",
        },
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()


# ---------------------------------------------------------------------
# bug 1: PATCH must recompute amount_eur and revalidate
# ---------------------------------------------------------------------


def test_patch_quantity_recomputes_amount_eur(client, auth_headers):
    account_id = _create_account(client, auth_headers)
    instrument_id = _create_instrument(client, auth_headers)
    txn = _buy(
        client, auth_headers, account_id, instrument_id, "patch-recompute",
        "2024-01-10", "5", "110.00",
    )
    assert txn["amount_eur"] == "550.00"

    patched = client.patch(
        f"/api/transactions/{txn['id']}", json={"quantity": "1"}, headers=auth_headers
    )
    assert patched.status_code == 200
    assert patched.json()["amount_eur"] == "110.00"


def test_patch_price_recomputes_amount_eur(client, auth_headers):
    account_id = _create_account(client, auth_headers)
    instrument_id = _create_instrument(client, auth_headers)
    txn = _buy(
        client, auth_headers, account_id, instrument_id, "patch-price",
        "2024-01-10", "5", "100.00",
    )
    assert txn["amount_eur"] == "500.00"

    patched = client.patch(
        f"/api/transactions/{txn['id']}", json={"price": "120.00"}, headers=auth_headers
    )
    assert patched.status_code == 200
    assert patched.json()["amount_eur"] == "600.00"


def test_patch_to_a_future_date_is_rejected(client, auth_headers):
    account_id = _create_account(client, auth_headers)
    instrument_id = _create_instrument(client, auth_headers)
    txn = _buy(
        client, auth_headers, account_id, instrument_id, "patch-future-date",
        "2024-01-10", "5", "100.00",
    )

    patched = client.patch(
        f"/api/transactions/{txn['id']}", json={"date": "2999-01-01"}, headers=auth_headers
    )
    assert patched.status_code == 422
    assert patched.json()["detail"]["code"] == "future_date"

    # Rejected — the original row (and its amount_eur) must be untouched.
    unchanged = client.get(
        "/api/transactions", params={"account_id": account_id}, headers=auth_headers
    ).json()
    assert unchanged[0]["date"] == "2024-01-10"
    assert unchanged[0]["amount_eur"] == "500.00"


# ---------------------------------------------------------------------
# bug 2: PATCH/DELETE must not leave the ledger unreplayable
# ---------------------------------------------------------------------


def test_patch_reducing_quantity_below_a_later_sell_is_rejected(client, auth_headers):
    account_id = _create_account(client, auth_headers)
    instrument_id = _create_instrument(client, auth_headers)
    buy = _buy(
        client, auth_headers, account_id, instrument_id, "patch-holdings-buy",
        "2024-01-10", "5", "100.00",
    )
    _sell(
        client, auth_headers, account_id, instrument_id, "patch-holdings-sell",
        "2024-06-01", "5", "600.00",
    )

    patched = client.patch(
        f"/api/transactions/{buy['id']}", json={"quantity": "1"}, headers=auth_headers
    )
    assert patched.status_code == 422
    assert patched.json()["detail"]["code"] == "edit_breaks_holdings"

    # Read endpoints must still work — the rejected edit must not have
    # been partially applied.
    positions = client.get("/api/positions", headers=auth_headers)
    assert positions.status_code == 200


def test_delete_of_a_buy_consumed_by_a_later_sell_is_rejected(client, auth_headers):
    account_id = _create_account(client, auth_headers)
    instrument_id = _create_instrument(client, auth_headers)
    buy = _buy(
        client, auth_headers, account_id, instrument_id, "delete-holdings-buy",
        "2024-01-10", "5", "100.00",
    )
    _sell(
        client, auth_headers, account_id, instrument_id, "delete-holdings-sell",
        "2024-06-01", "5", "600.00",
    )

    deleted = client.delete(f"/api/transactions/{buy['id']}", headers=auth_headers)
    assert deleted.status_code == 422
    assert deleted.json()["detail"]["code"] == "delete_breaks_holdings"

    positions = client.get("/api/positions", headers=auth_headers)
    assert positions.status_code == 200
    still_there = client.get(
        "/api/transactions", params={"account_id": account_id}, headers=auth_headers
    ).json()
    assert len(still_there) == 2


def test_delete_of_an_unconsumed_buy_still_works(client, auth_headers):
    """Sanity check the fix isn't overzealous: deleting a BUY nothing
    depends on must still succeed."""
    account_id = _create_account(client, auth_headers)
    instrument_id = _create_instrument(client, auth_headers)
    buy = _buy(
        client, auth_headers, account_id, instrument_id, "delete-holdings-ok",
        "2024-01-10", "5", "100.00",
    )

    deleted = client.delete(f"/api/transactions/{buy['id']}", headers=auth_headers)
    assert deleted.status_code == 204


# ---------------------------------------------------------------------
# bug 3: DELETE /api/import-batches/{id} has the same hole
# ---------------------------------------------------------------------


def test_batch_rollback_blocked_when_another_batchs_sell_depends_on_it(
    client, auth_headers
):
    account_id = _create_account(client, auth_headers)
    instrument_id = _create_instrument(client, auth_headers)

    buy_batch = client.post(
        "/api/transactions/bulk",
        json={
            "dry_run": False,
            "transactions": [
                {
                    "external_id": "batch-rollback-buy",
                    "date": "2024-01-10",
                    "type": "BUY",
                    "account_id": account_id,
                    "instrument_id": instrument_id,
                    "quantity": "5",
                    "price": "100.00",
                    "currency": "EUR",
                }
            ],
        },
        headers=auth_headers,
    )
    batch_id = buy_batch.json()["import_batch_id"]
    assert batch_id is not None

    # A SELL booked afterwards, in its own (separate) batch, consumes
    # that BUY's lot.
    _sell(
        client, auth_headers, account_id, instrument_id, "batch-rollback-sell",
        "2024-06-01", "5", "600.00",
    )

    rollback = client.delete(f"/api/import-batches/{batch_id}", headers=auth_headers)
    assert rollback.status_code == 422
    assert rollback.json()["detail"]["code"] == "delete_breaks_holdings"

    positions = client.get("/api/positions", headers=auth_headers)
    assert positions.status_code == 200
    remaining = client.get(
        "/api/transactions", params={"account_id": account_id}, headers=auth_headers
    ).json()
    assert len(remaining) == 2
