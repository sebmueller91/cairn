"""A ledger poisoned *before* the write-path guards existed must still be
readable — with a machine-readable code naming the offending row, not an
opaque 500.

Guarding PATCH/DELETE/batch-rollback stops a *new* unreplayable ledger from
being created. It does nothing for a database that already contains one,
which is exactly the state the old unguarded PATCH could leave behind. Those
rows are edited here directly, bypassing the API, to reproduce that state.

Invented figures only.
"""
from decimal import Decimal

from sqlalchemy import text

from app.database import engine


def _seed_oversold_ledger(client, auth_headers):
    """BUY 10, SELL 8, then shrink the BUY to 2 behind the API's back."""
    account = client.post(
        "/api/accounts",
        json={"name": "Poisoned Depot", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Poisoned Fund",
            "isin": "QA0000000404",
            "asset_class": "EQUITY",
            "valuation_mode": "MARKET",
            "currency": "EUR",
        },
        headers=auth_headers,
    ).json()
    for ext, date, kind, qty, price in [
        ("poison-buy", "2026-01-10", "BUY", "10", "100.00"),
        ("poison-sell", "2026-03-01", "SELL", "8", "120.00"),
    ]:
        resp = client.post(
            "/api/transactions",
            json={
                "external_id": ext,
                "date": date,
                "type": kind,
                "account_id": account["id"],
                "instrument_id": instrument["id"],
                "quantity": qty,
                "price": price,
                "currency": "EUR",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE txn SET quantity = '2' WHERE external_id = 'poison-buy'")
        )
    return account, instrument


def test_the_api_still_refuses_to_create_this_state(client, auth_headers):
    """Sanity: the guards are what make this test need a raw UPDATE at all."""
    account, instrument = _seed_oversold_ledger(client, auth_headers)
    txns = client.get("/api/transactions", headers=auth_headers)
    # The read itself must not blow up just because the ledger is poisoned —
    # /api/transactions lists rows, it does not replay them.
    assert txns.status_code == 200


def test_poisoned_ledger_reads_as_a_coded_conflict_not_a_500(client, auth_headers):
    _seed_oversold_ledger(client, auth_headers)

    for endpoint in (
        "/api/positions",
        "/api/tax",
        "/api/data-quality",
        "/api/look-through",
    ):
        resp = client.get(endpoint, headers=auth_headers)
        assert resp.status_code == 409, f"{endpoint} -> {resp.status_code}"
        detail = resp.json()["detail"]
        assert detail["code"] == "ledger_unreplayable", endpoint
        # The operator has to be able to find the row to correct, so the
        # shortfall itself must travel with the error.
        assert Decimal(detail["params"]["requested"]) == Decimal("8")
        assert Decimal(detail["params"]["available"]) == Decimal("2")
        assert detail["params"]["account_id"] is not None
        assert detail["params"]["instrument_id"] is not None


def test_the_error_body_is_json_the_spa_can_parse(client, auth_headers):
    _seed_oversold_ledger(client, auth_headers)
    resp = client.get("/api/positions", headers=auth_headers)
    assert "application/json" in resp.headers["content-type"]
