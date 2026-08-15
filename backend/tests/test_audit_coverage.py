"""Every write endpoint outside transactions/import-batches (already
covered) must also leave an audit_log row — see app/audit.py. This is a
representative sample, not exhaustive: one test per router family that
writes financially meaningful state. Invented ISINs/amounts only, per
AGENTS.md."""

from app.models import AuditLog


def _log_for(db_session, entity, entity_id):
    return (
        db_session.query(AuditLog)
        .filter(AuditLog.entity == entity, AuditLog.entity_id == str(entity_id))
        .all()
    )


def test_account_create_and_delete_are_audited(client, auth_headers, db_session):
    account = client.post(
        "/api/accounts",
        json={"name": "Audit Test Brokerage", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()

    logs = _log_for(db_session, "account", account["id"])
    assert [entry.action for entry in logs] == ["create"]
    assert logs[0].actor.value == "agent"
    assert logs[0].payload_hash == "n/a"

    resp = client.delete(f"/api/accounts/{account['id']}", headers=auth_headers)
    assert resp.status_code == 204

    logs = _log_for(db_session, "account", account["id"])
    assert [entry.action for entry in logs] == ["create", "delete"]


def test_instrument_create_is_audited(client, auth_headers, db_session):
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Audit Test ETF",
            "isin": "XX0000009001",
            "asset_class": "EQUITY",
            "valuation_mode": "MARKET",
            "currency": "EUR",
        },
        headers=auth_headers,
    ).json()

    logs = _log_for(db_session, "instrument", instrument["id"])
    assert [entry.action for entry in logs] == ["create"]


def test_valuation_anchor_create_is_audited(client, auth_headers, db_session):
    house = client.post(
        "/api/instruments",
        json={
            "name": "Audit Test House",
            "asset_class": "REAL_ESTATE",
            "valuation_mode": "ANCHORED",
            "currency": "EUR",
        },
        headers=auth_headers,
    ).json()
    anchor = client.post(
        "/api/valuations",
        json={
            "instrument_id": house["id"],
            "date": "2020-01-01",
            "value_eur": "400000.00",
            "method": "purchase",
        },
        headers=auth_headers,
    ).json()

    logs = _log_for(db_session, "valuation_anchor", anchor["id"])
    assert [entry.action for entry in logs] == ["create"]


def test_loan_create_is_audited(client, auth_headers, db_session):
    loan_account = client.post(
        "/api/accounts",
        json={"name": "Audit Test Mortgage", "type": "LOAN", "currency": "EUR"},
        headers=auth_headers,
    ).json()
    loan = client.post(
        "/api/loans",
        json={
            "account_id": loan_account["id"],
            "principal": "100000.00",
            "rate_pct": "6.0",
            "start_date": "2024-01-01",
            "monthly_payment": "1000.00",
        },
        headers=auth_headers,
    ).json()

    logs = _log_for(db_session, "loan", loan["id"])
    assert [entry.action for entry in logs] == ["create"]


def test_cpi_upsert_is_audited(client, auth_headers, db_session):
    client.post(
        "/api/cpi", json={"date": "2020-01-01", "index_value": "100.0"}, headers=auth_headers
    )
    logs = _log_for(db_session, "cpi_index_point", "2020-01-01")
    assert [entry.action for entry in logs] == ["create"]

    # Re-posting the same date upserts the existing row -> "update".
    client.post(
        "/api/cpi", json={"date": "2020-01-01", "index_value": "101.0"}, headers=auth_headers
    )
    logs = _log_for(db_session, "cpi_index_point", "2020-01-01")
    assert [entry.action for entry in logs] == ["create", "update"]


def test_composition_put_is_audited(client, auth_headers, db_session):
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Audit Test World ETF",
            "isin": "XX0000009002",
            "asset_class": "EQUITY",
            "valuation_mode": "MARKET",
            "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]

    resp = client.put(
        f"/api/instruments/{instrument}/composition",
        json={"dimension": "region", "breakdown": {"North America": "60", "Europe": "40"}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    logs = _log_for(db_session, "etf_composition", instrument)
    assert [entry.action for entry in logs] == ["update"]
    assert logs[0].diff_json is not None


def test_targets_put_is_audited(client, auth_headers, db_session):
    resp = client.put(
        "/api/allocation/targets",
        json={"targets": {"EQUITY": "60", "BOND": "40"}},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    logs = _log_for(db_session, "target_allocation", "target_allocation")
    assert [entry.action for entry in logs] == ["update"]


def test_price_source_create_is_audited(client, auth_headers, db_session):
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Audit Test Price Source ETF",
            "isin": "XX0000009003",
            "ticker": "AUDT.DE",
            "asset_class": "EQUITY",
            "valuation_mode": "MARKET",
            "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]

    source = client.post(
        f"/api/instruments/{instrument}/price-sources",
        json={"provider": "stooq", "provider_symbol": "AUDT.DE", "priority": 0},
        headers=auth_headers,
    ).json()

    logs = _log_for(db_session, "price_source", source["id"])
    assert [entry.action for entry in logs] == ["create"]


def test_house_index_upsert_is_audited(client, auth_headers, db_session):
    client.post(
        "/api/house-index",
        json={"series": "audit-test-series", "date": "2024-01-01", "index_value": "110.5"},
        headers=auth_headers,
    )
    logs = _log_for(db_session, "house_price_index_point", "audit-test-series:2024-01-01")
    assert [entry.action for entry in logs] == ["create"]

    client.post(
        "/api/house-index",
        json={"series": "audit-test-series", "date": "2024-01-01", "index_value": "111.0"},
        headers=auth_headers,
    )
    logs = _log_for(db_session, "house_price_index_point", "audit-test-series:2024-01-01")
    assert [entry.action for entry in logs] == ["create", "update"]
