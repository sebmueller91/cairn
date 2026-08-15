"""spec 7.4. Invented ISINs and quantities only, per AGENTS.md."""


def _setup(client, headers, isin="XX0000000500"):
    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=headers,
    ).json()
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Test ETF",
            "isin": isin,
            "asset_class": "EQUITY",
            "valuation_mode": "MARKET",
            "currency": "EUR",
        },
        headers=headers,
    ).json()
    client.post(
        "/api/transactions",
        json={
            "external_id": "rec-buy-1",
            "date": "2024-01-01",
            "type": "BUY",
            "account_id": account["id"],
            "instrument_id": instrument["id"],
            "quantity": "412.3",
            "price": "10.00",
            "currency": "EUR",
        },
        headers=headers,
    )
    return account, instrument


def test_reconcile_matching_holding(client, auth_headers):
    account, instrument = _setup(client, auth_headers)

    resp = client.post(
        "/api/reconcile",
        json={
            "account": "Portfolio A",
            "as_of": "2026-08-12",
            "holdings": [{"isin": instrument["isin"], "quantity": "412.3"}],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    diffs = resp.json()["differences"]
    assert len(diffs) == 1
    assert diffs[0]["matched"] is True
    assert diffs[0]["delta"] == "0.0"


def test_reconcile_reports_quantity_mismatch(client, auth_headers):
    account, instrument = _setup(client, auth_headers, isin="XX0000000501")

    resp = client.post(
        "/api/reconcile",
        json={
            "account": "Portfolio A",
            "as_of": "2026-08-12",
            # statement shows more than the ledger has -> a missed
            # savings-plan execution, exactly the scenario spec 7.4 names
            "holdings": [{"isin": instrument["isin"], "quantity": "420.0"}],
        },
        headers=auth_headers,
    )
    diffs = resp.json()["differences"]
    assert diffs[0]["matched"] is False
    assert diffs[0]["computed_quantity"] == "412.3"
    assert diffs[0]["delta"] == "7.7"


def test_reconcile_unknown_isin(client, auth_headers):
    account, _ = _setup(client, auth_headers, isin="XX0000000502")

    resp = client.post(
        "/api/reconcile",
        json={
            "account": "Portfolio A",
            "as_of": "2026-08-12",
            "holdings": [{"isin": "XX9999999999", "quantity": "5"}],
        },
        headers=auth_headers,
    )
    diffs = resp.json()["differences"]
    # unknown ISIN AND the real held position missing from the statement
    assert len(diffs) == 2
    unknown = next(d for d in diffs if d["isin"] == "XX9999999999")
    assert unknown["note"] == "unknown_isin"
    missing = next(d for d in diffs if d["note"] == "missing_from_report")
    assert missing["computed_quantity"] == "412.3"


def test_reconcile_unknown_account_404s(client, auth_headers):
    resp = client.post(
        "/api/reconcile",
        json={"account": "Nonexistent", "as_of": "2026-08-12", "holdings": []},
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "account_not_found"
