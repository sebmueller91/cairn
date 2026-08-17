"""Invented ISINs and amounts only, per AGENTS.md."""

import csv
import io
import json
import zipfile
from datetime import date
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


def _setup_hand_entered_data(client, auth_headers, db_session, instrument):
    """Seeds one row each of the hand-entered, irreplaceable data the
    export must not drop: a CPI point, a house price index point, an
    ETF composition row, and a target allocation setting."""
    from app.models import CpiIndexPoint, HousePriceIndexPoint

    db_session.add(CpiIndexPoint(date=date(2024, 1, 1), index_value=Decimal("110.5")))
    db_session.add(
        HousePriceIndexPoint(
            series="EFH_DE", date=date(2024, 1, 1), index_value=Decimal("142.3")
        )
    )
    db_session.commit()

    client.put(
        f"/api/instruments/{instrument}/composition",
        json={"dimension": "region", "breakdown": {"Europe": "100"}},
        headers=auth_headers,
    )
    client.put(
        "/api/allocation/targets",
        json={"targets": {"EQUITY": "100"}},
        headers=auth_headers,
    )


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
        "cpi_index_points.csv", "house_price_index_points.csv",
        "etf_compositions.csv", "target_allocation.csv",
    }

    export_json = json.loads(zf.read("export.json"))
    assert len(export_json["transactions"]) == 1

    reader = csv.DictReader(io.StringIO(zf.read("transactions.csv").decode("utf-8")))
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["amount_eur"] == "1000.00"
    assert rows[0]["type"] == "BUY"


def test_export_includes_hand_entered_irreplaceable_data(client, auth_headers, db_session):
    """Bug: cpi_index_point, house_price_index_point, etf_composition, and
    the target_allocation setting are all hand-entered and not
    refetchable, yet the export silently dropped them. Assert all four
    survive into both export.json and the ZIP's CSVs."""
    from app.database import SessionLocal
    from app.export_service import build_export, build_export_zip

    account, instrument = _setup(client, auth_headers)
    _setup_hand_entered_data(client, auth_headers, db_session, instrument)

    db = SessionLocal()
    try:
        data = build_export(db)
    finally:
        db.close()

    assert data["cpi_index_points"] == [
        {"date": "2024-01-01", "index_value": "110.5"}
    ]
    assert data["house_price_index_points"] == [
        {"series": "EFH_DE", "date": "2024-01-01", "index_value": "142.3"}
    ]
    # updated_at travels with the breakdown on purpose: restoring without
    # it would reset the staleness clock and make a years-old breakdown
    # look freshly entered.
    assert len(data["etf_compositions"]) == 1
    composition = data["etf_compositions"][0]
    assert composition["instrument_id"] == instrument
    assert composition["dimension"] == "region"
    assert composition["category"] == "Europe"
    assert composition["weight_pct"] == "100"
    assert composition["updated_at"] is not None
    assert data["target_allocation"] == [
        {"asset_class": "EQUITY", "target_pct": "100"}
    ]

    db = SessionLocal()
    try:
        content = build_export_zip(db)
    finally:
        db.close()

    zf = zipfile.ZipFile(io.BytesIO(content))

    cpi_rows = list(csv.DictReader(io.StringIO(zf.read("cpi_index_points.csv").decode("utf-8"))))
    assert cpi_rows == [{"date": "2024-01-01", "index_value": "110.5"}]

    house_rows = list(
        csv.DictReader(io.StringIO(zf.read("house_price_index_points.csv").decode("utf-8")))
    )
    assert house_rows == [{"series": "EFH_DE", "date": "2024-01-01", "index_value": "142.3"}]

    etf_rows = list(csv.DictReader(io.StringIO(zf.read("etf_compositions.csv").decode("utf-8"))))
    assert len(etf_rows) == 1
    assert etf_rows[0]["instrument_id"] == str(instrument)
    assert etf_rows[0]["dimension"] == "region"
    assert etf_rows[0]["category"] == "Europe"
    assert etf_rows[0]["weight_pct"] == "100"
    assert etf_rows[0]["updated_at"]

    target_rows = list(
        csv.DictReader(io.StringIO(zf.read("target_allocation.csv").decode("utf-8")))
    )
    assert target_rows == [{"asset_class": "EQUITY", "target_pct": "100"}]


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
