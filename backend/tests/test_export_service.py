"""Invented ISINs and amounts only, per AGENTS.md."""

import csv
import io
import json
import zipfile
from decimal import Decimal


def _setup(client, auth_headers):
    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Test ETF", "isin": "XX0000001000",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    client.post(
        "/api/transactions",
        json={
            "external_id": "export-buy-1", "date": "2024-01-01", "type": "BUY",
            "account_id": account, "instrument_id": instrument,
            "quantity": "10", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    return account, instrument


def test_build_export_includes_every_written_row(client, auth_headers):
    from app.database import SessionLocal
    from app.export_service import build_export

    account, instrument = _setup(client, auth_headers)

    db = SessionLocal()
    try:
        data = build_export(db)
    finally:
        db.close()

    assert len(data["accounts"]) == 1
    assert data["accounts"][0]["id"] == account
    assert data["accounts"][0]["type"] == "BROKERAGE"
    assert len(data["instruments"]) == 1
    assert data["instruments"][0]["id"] == instrument
    assert len(data["transactions"]) == 1
    assert data["transactions"][0]["amount_eur"] == "1000.00"
    assert data["valuation_anchors"] == []
    assert data["loans"] == []


def test_build_export_zip_contains_matching_csv_and_json(client, auth_headers):
    from app.database import SessionLocal
    from app.export_service import build_export_zip

    _setup(client, auth_headers)

    db = SessionLocal()
    try:
        content = build_export_zip(db)
    finally:
        db.close()

    zf = zipfile.ZipFile(io.BytesIO(content))
    names = set(zf.namelist())
    assert names == {
        "export.json", "accounts.csv", "instruments.csv",
        "transactions.csv", "valuation_anchors.csv", "loans.csv",
    }

    export_json = json.loads(zf.read("export.json"))
    assert len(export_json["transactions"]) == 1

    reader = csv.DictReader(io.StringIO(zf.read("transactions.csv").decode("utf-8")))
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["amount_eur"] == "1000.00"
    assert rows[0]["type"] == "BUY"


def test_export_full_endpoint_returns_a_zip(client, auth_headers):
    _setup(client, auth_headers)

    resp = client.get("/api/export/full", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "attachment" in resp.headers["content-disposition"]

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert "export.json" in zf.namelist()


def test_export_full_requires_auth(client):
    resp = client.get("/api/export/full")
    assert resp.status_code == 401
