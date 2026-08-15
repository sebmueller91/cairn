"""End-to-end agent workflow per docs/agent-workflows.md scenario 1:
dry run -> visual check -> commit -> reconcile against the statement's
own closing holdings. Invented data only, per AGENTS.md."""


def test_import_annual_statement_then_reconcile(client, auth_headers):
    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Test World ETF",
            "isin": "XX0000000600",
            "ticker": "TEST.DE",
            "asset_class": "EQUITY",
            "valuation_mode": "MARKET",
            "currency": "EUR",
        },
        headers=auth_headers,
    ).json()

    # A statement listing three savings-plan executions and one partial
    # sale — external_ids built the way agent-workflows.md prescribes:
    # <account>-<date>-<isin>-<type>-<n>.
    statement_rows = [
        {
            "external_id": "portfolioA-2025-01-14-XX0000000600-buy-1",
            "date": "2025-01-14",
            "type": "BUY",
            "account_id": account["id"],
            "instrument_id": instrument["id"],
            "quantity": "12.5",
            "price": "92.34",
            "currency": "EUR",
            "fees": "1.50",
            "note": "savings plan execution",
            "source": "agent",
        },
        {
            "external_id": "portfolioA-2025-02-14-XX0000000600-buy-1",
            "date": "2025-02-14",
            "type": "BUY",
            "account_id": account["id"],
            "instrument_id": instrument["id"],
            "quantity": "12.8",
            "price": "90.10",
            "currency": "EUR",
            "fees": "1.50",
            "note": "savings plan execution",
            "source": "agent",
        },
        {
            "external_id": "portfolioA-2025-03-14-XX0000000600-buy-1",
            "date": "2025-03-14",
            "type": "BUY",
            "account_id": account["id"],
            "instrument_id": instrument["id"],
            "quantity": "13.1",
            "price": "88.00",
            "currency": "EUR",
            "fees": "1.50",
            "note": "savings plan execution",
            "source": "agent",
        },
        {
            "external_id": "portfolioA-2025-06-01-XX0000000600-sell-1",
            "date": "2025-06-01",
            "type": "SELL",
            "account_id": account["id"],
            "instrument_id": instrument["id"],
            "quantity": "5.0",
            "price": "95.00",
            "currency": "EUR",
            "fees": "1.50",
            "note": "partial sale",
            "source": "agent",
        },
    ]

    # 1. dry run — must write nothing
    dry_run = client.post(
        "/api/transactions/bulk",
        json={
            "dry_run": True,
            "import_batch_label": "Portfolio A annual statement 2025",
            "transactions": statement_rows,
        },
        headers=auth_headers,
    )
    assert dry_run.status_code == 200
    assert dry_run.json()["import_batch_id"] is None
    assert all(r["outcome"] == "would_create" for r in dry_run.json()["rows"])
    assert (
        client.get(
            "/api/transactions", params={"account_id": account["id"]}, headers=auth_headers
        ).json()
        == []
    )

    # 2. visual check (the dry-run response above is what an agent shows
    # the user) -> 3. commit the identical payload
    commit = client.post(
        "/api/transactions/bulk",
        json={
            "dry_run": False,
            "import_batch_label": "Portfolio A annual statement 2025",
            "transactions": statement_rows,
        },
        headers=auth_headers,
    )
    assert commit.status_code == 200
    assert all(r["outcome"] == "created" for r in commit.json()["rows"])

    # 4. reconcile against the statement's own printed closing holdings:
    # 12.5 + 12.8 + 13.1 - 5.0 = 33.4
    reconcile = client.post(
        "/api/reconcile",
        json={
            "account": "Portfolio A",
            "as_of": "2025-12-31",
            "holdings": [{"isin": "XX0000000600", "quantity": "33.4"}],
        },
        headers=auth_headers,
    )
    assert reconcile.status_code == 200
    diffs = reconcile.json()["differences"]
    assert len(diffs) == 1
    assert diffs[0]["matched"] is True, diffs

    # 5. re-sending the exact same statement (an agent retry) must not
    # duplicate anything
    resend = client.post(
        "/api/transactions/bulk",
        json={"dry_run": False, "transactions": statement_rows},
        headers=auth_headers,
    )
    assert all(r["outcome"] == "duplicate_skipped" for r in resend.json()["rows"])
    positions = client.get(
        "/api/positions", params={"account_id": account["id"]}, headers=auth_headers
    ).json()
    assert positions[0]["quantity"] == "33.4"
