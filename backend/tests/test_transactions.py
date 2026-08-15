"""API-level golden dataset (ADR 0013): loaded through the real
POST /api/transactions/bulk endpoint, not seeded directly into the DB, so
idempotency/dry-run/validation are exercised alongside the ledger math.
Invented account/instrument/amounts only, per AGENTS.md.
"""


def _create_account(client, headers, name="Portfolio A", type_="BROKERAGE"):
    r = client.post(
        "/api/accounts",
        json={"name": name, "type": type_, "currency": "EUR"},
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()["id"]


def _create_instrument(client, headers, name="Test World ETF", isin="XX0000000010"):
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


def test_dry_run_writes_nothing(client, auth_headers):
    account_id = _create_account(client, auth_headers)
    instrument_id = _create_instrument(client, auth_headers)

    resp = client.post(
        "/api/transactions/bulk",
        json={
            "dry_run": True,
            "transactions": [
                {
                    "external_id": "t-buy-1",
                    "date": "2024-01-10",
                    "type": "BUY",
                    "account_id": account_id,
                    "instrument_id": instrument_id,
                    "quantity": "10",
                    "price": "100.00",
                    "currency": "EUR",
                    "fees": "1.50",
                }
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["import_batch_id"] is None
    assert body["rows"][0]["outcome"] == "would_create"
    assert body["rows"][0]["transaction"]["amount_eur"] == "1001.50"

    listed = client.get(
        "/api/transactions", params={"account_id": account_id}, headers=auth_headers
    )
    assert listed.json() == []


def test_commit_then_resend_is_idempotent(client, auth_headers):
    account_id = _create_account(client, auth_headers)
    instrument_id = _create_instrument(client, auth_headers)
    payload = {
        "external_id": "t-buy-2",
        "date": "2024-01-10",
        "type": "BUY",
        "account_id": account_id,
        "instrument_id": instrument_id,
        "quantity": "10",
        "price": "100.00",
        "currency": "EUR",
        "fees": "1.50",
    }

    first = client.post(
        "/api/transactions/bulk",
        json={"dry_run": False, "transactions": [payload]},
        headers=auth_headers,
    )
    assert first.status_code == 200
    assert first.json()["rows"][0]["outcome"] == "created"
    batch_id = first.json()["import_batch_id"]
    assert batch_id is not None

    # identical resend -> no duplicate row, same batch's txn returned
    second = client.post(
        "/api/transactions/bulk",
        json={"dry_run": False, "transactions": [payload]},
        headers=auth_headers,
    )
    assert second.json()["rows"][0]["outcome"] == "duplicate_skipped"

    listed = client.get(
        "/api/transactions", params={"account_id": account_id}, headers=auth_headers
    )
    assert len(listed.json()) == 1

    # same external_id, different content -> conflict, not a silent overwrite
    conflicting = {**payload, "quantity": "999"}
    third = client.post(
        "/api/transactions/bulk",
        json={"dry_run": False, "transactions": [conflicting]},
        headers=auth_headers,
    )
    assert third.json()["rows"][0]["outcome"] == "error"
    assert third.json()["rows"][0]["error"]["code"] == "external_id_conflict"


def test_selling_more_than_held_is_rejected(client, auth_headers):
    account_id = _create_account(client, auth_headers)
    instrument_id = _create_instrument(client, auth_headers)

    resp = client.post(
        "/api/transactions/bulk",
        json={
            "dry_run": False,
            "transactions": [
                {
                    "external_id": "t-sell-oversell",
                    "date": "2024-01-10",
                    "type": "SELL",
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
    row = resp.json()["rows"][0]
    assert row["outcome"] == "error"
    assert row["error"]["code"] == "sell_exceeds_holding"


def test_import_batch_rollback_via_transaction_delete(client, auth_headers):
    # Batch-level DELETE is task 19/21 territory; for now confirm the
    # single-transaction delete works and is audited.
    account_id = _create_account(client, auth_headers)
    instrument_id = _create_instrument(client, auth_headers)
    create = client.post(
        "/api/transactions",
        json={
            "external_id": "t-buy-single",
            "date": "2024-01-10",
            "type": "BUY",
            "account_id": account_id,
            "instrument_id": instrument_id,
            "quantity": "10",
            "price": "100.00",
            "currency": "EUR",
        },
        headers=auth_headers,
    )
    assert create.status_code == 201
    txn_id = create.json()["id"]

    deleted = client.delete(f"/api/transactions/{txn_id}", headers=auth_headers)
    assert deleted.status_code == 204

    missing = client.get(
        "/api/transactions", params={"account_id": account_id}, headers=auth_headers
    )
    assert missing.json() == []


def test_single_post_dry_run_writes_nothing(client, auth_headers):
    """Bug: POST /api/transactions accepted a `dry_run` field/param that
    the endpoint silently ignored (Pydantic v2 drops unknown fields by
    default), so a validate-only request actually booked the transaction.
    dry_run must (a) leave the txn table completely unchanged and (b)
    return a response that cannot be mistaken for a real booking."""
    account_id = _create_account(client, auth_headers)
    instrument_id = _create_instrument(client, auth_headers)
    payload = {
        "external_id": "t-buy-dry-run",
        "date": "2024-01-10",
        "type": "BUY",
        "account_id": account_id,
        "instrument_id": instrument_id,
        "quantity": "10",
        "price": "100.00",
        "currency": "EUR",
        "fees": "1.50",
    }

    dry = client.post(
        "/api/transactions", params={"dry_run": "true"}, json=payload, headers=auth_headers
    )
    assert dry.status_code == 200  # never the 201 a real create returns
    body = dry.json()
    assert body["dry_run"] is True
    assert body["outcome"] == "would_create"
    assert body["transaction"]["amount_eur"] == "1001.50"

    # Nothing persisted: not visible via list...
    listed = client.get(
        "/api/transactions", params={"account_id": account_id}, headers=auth_headers
    )
    assert listed.json() == []

    # ...and a real POST with the same external_id afterwards is a fresh
    # create, not a duplicate/conflict — proving the dry run wrote nothing.
    real = client.post("/api/transactions", json=payload, headers=auth_headers)
    assert real.status_code == 201  # bare TransactionRead, not the dry-run envelope
    assert real.json()["amount_eur"] == "1001.50"

    listed_after = client.get(
        "/api/transactions", params={"account_id": account_id}, headers=auth_headers
    )
    assert len(listed_after.json()) == 1


def test_single_post_dry_run_still_validates(client, auth_headers):
    account_id = _create_account(client, auth_headers)
    instrument_id = _create_instrument(client, auth_headers)

    resp = client.post(
        "/api/transactions",
        params={"dry_run": "true"},
        json={
            "external_id": "t-sell-dry-run-oversell",
            "date": "2024-01-10",
            "type": "SELL",
            "account_id": account_id,
            "instrument_id": instrument_id,
            "quantity": "5",
            "price": "100.00",
            "currency": "EUR",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "sell_exceeds_holding"

    listed = client.get(
        "/api/transactions", params={"account_id": account_id}, headers=auth_headers
    )
    assert listed.json() == []


def test_list_transactions_filters_by_from_to(client, auth_headers):
    """Bug: the router only accepted date_from/date_to while both spec 7.1
    and the MCP server send from/to — FastAPI drops unknown query params,
    so date filtering silently did nothing over the wire."""
    account_id = _create_account(client, auth_headers)
    instrument_id = _create_instrument(client, auth_headers)
    for i, d in enumerate(["2024-01-05", "2024-02-05", "2024-03-05"]):
        r = client.post(
            "/api/transactions",
            json={
                "external_id": f"t-from-to-{i}",
                "date": d,
                "type": "BUY",
                "account_id": account_id,
                "instrument_id": instrument_id,
                "quantity": "1",
                "price": "10.00",
                "currency": "EUR",
            },
            headers=auth_headers,
        )
        assert r.status_code == 201

    resp = client.get(
        "/api/transactions",
        params={"account_id": account_id, "from": "2024-01-15", "to": "2024-02-15"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    dates = [row["date"] for row in resp.json()]
    assert dates == ["2024-02-05"]


def test_full_golden_dataset_scenario(client, auth_headers):
    """purchase, partial sale, split, dividend, FX purchase, in-kind
    transfer — spec ch. 10's list, minus the provisional-opening-balance/
    supersede case (task 21)."""
    account_a = _create_account(client, auth_headers, name="Portfolio A")
    account_b = _create_account(client, auth_headers, name="Portfolio B")
    instrument = _create_instrument(client, auth_headers)

    # FX purchase: a US-listed instrument, priced in USD
    us_instrument = client.post(
        "/api/instruments",
        json={
            "name": "Test US ETF",
            "isin": "XX0000000099",
            "asset_class": "EQUITY",
            "valuation_mode": "MARKET",
            "currency": "USD",
        },
        headers=auth_headers,
    ).json()["id"]

    rows = [
        {
            "external_id": "g-buy-1",
            "date": "2024-01-10",
            "type": "BUY",
            "account_id": account_a,
            "instrument_id": instrument,
            "quantity": "20",
            "price": "100.00",
            "currency": "EUR",
            "fees": "2.00",
        },
        {
            "external_id": "g-sell-1",
            "date": "2024-03-01",
            "type": "SELL",
            "account_id": account_a,
            "instrument_id": instrument,
            "quantity": "5",
            "price": "110.00",
            "currency": "EUR",
            "fees": "1.00",
        },
        {
            "external_id": "g-split-1",
            "date": "2024-04-01",
            "type": "SPLIT",
            "account_id": account_a,
            "instrument_id": instrument,
            "currency": "EUR",
            "split_ratio": "2",
        },
        {
            "external_id": "g-div-1",
            "date": "2024-05-01",
            "type": "DIVIDEND",
            "account_id": account_a,
            "instrument_id": instrument,
            "currency": "EUR",
            "amount": "12.00",
        },
        {
            "external_id": "g-transfer-1",
            "date": "2024-06-01",
            "type": "TRANSFER",
            "account_id": account_a,
            "counter_account_id": account_b,
            "instrument_id": instrument,
            "quantity": "10",
            "currency": "EUR",
        },
        {
            "external_id": "g-fx-buy-1",
            "date": "2024-07-01",
            "type": "BUY",
            "account_id": account_a,
            "instrument_id": us_instrument,
            "quantity": "3",
            "price": "50.00",
            "currency": "USD",
            "fx_rate": "0.90",  # 1 USD = 0.90 EUR
            "fees": "1.00",
        },
    ]

    result = client.post(
        "/api/transactions/bulk",
        json={"dry_run": False, "import_batch_label": "golden dataset", "transactions": rows},
        headers=auth_headers,
    )
    assert result.status_code == 200
    outcomes = [r["outcome"] for r in result.json()["rows"]]
    assert outcomes == ["created"] * len(rows)

    # Chronological order matters: 20 bought -> 5 sold (15 left) -> split
    # 2:1 (30 left) -> 10 transferred out (20 left in A, 10 now in B).
    positions = client.get(
        "/api/positions", params={"account_id": account_a}, headers=auth_headers
    ).json()
    pos_a = next(p for p in positions if p["instrument_id"] == instrument)
    assert pos_a["quantity"] == "20"
    assert pos_a["cost_basis_eur"] == "1001.00"
    assert pos_a["realized_pl_eur"] == "48.50"  # from the SELL, before the split

    pos_b = client.get(
        "/api/positions", params={"account_id": account_b}, headers=auth_headers
    ).json()
    assert pos_b[0]["quantity"] == "10"
    assert pos_b[0]["cost_basis_eur"] == "500.50"

    # instrument-level view aggregates both accounts back to 30
    by_instrument = client.get(
        "/api/positions", params={"group_by": "instrument"}, headers=auth_headers
    ).json()
    total = next(p for p in by_instrument if p["instrument_id"] == instrument)
    assert total["quantity"] == "30"

    # FX buy: 3 * 50 USD * 0.90 + 1.00 USD fee * 0.90 = 135.00 + 0.90 = 135.90 EUR
    us_positions = client.get(
        "/api/positions", params={"account_id": account_a}, headers=auth_headers
    ).json()
    us_pos = next(p for p in us_positions if p["instrument_id"] == us_instrument)
    assert us_pos["cost_basis_eur"] == "135.90"
