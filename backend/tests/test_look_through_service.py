"""Invented ISINs, quantities, and amounts only, per AGENTS.md."""

from datetime import date
from decimal import Decimal


def test_look_through_splits_etf_and_falls_back_to_own_region(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.look_through_service import compute_look_through
    from app.models import EtfComposition, PricePoint

    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    etf = client.post(
        "/api/instruments",
        json={
            "name": "World ETF", "isin": "XX0000001200",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    stock = client.post(
        "/api/instruments",
        json={
            "name": "Single Stock", "isin": "XX0000001201",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
            "region": "Europe",
        },
        headers=auth_headers,
    ).json()["id"]

    db_session.add(EtfComposition(instrument_id=etf, dimension="region", category="North America", weight_pct=Decimal(60)))
    db_session.add(EtfComposition(instrument_id=etf, dimension="region", category="Europe", weight_pct=Decimal(40)))
    for iid, price in [(etf, "100.00"), (stock, "50.00")]:
        db_session.add(
            PricePoint(
                instrument_id=iid, date=date(2024, 1, 1), close=Decimal(price),
                currency="EUR", provider="test", quality="ok",
            )
        )
    db_session.commit()

    client.post(
        "/api/transactions",
        json={
            "external_id": "lt-buy-etf", "date": "2024-01-01", "type": "BUY",
            "account_id": account, "instrument_id": etf,
            "quantity": "10", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    client.post(
        "/api/transactions",
        json={
            "external_id": "lt-buy-stock", "date": "2024-01-01", "type": "BUY",
            "account_id": account, "instrument_id": stock,
            "quantity": "5", "price": "50.00", "currency": "EUR",
        },
        headers=auth_headers,
    )

    db = SessionLocal()
    try:
        rows = compute_look_through(db, "region", as_of=date(2024, 1, 1))
    finally:
        db.close()

    by_category = {r.category: r.value_eur for r in rows}
    # ETF: 1000 total -> 600 NA / 400 EU. Stock: 250, all to its own
    # region (Europe) -> EU total = 400 + 250 = 650.
    assert by_category["North America"] == Decimal("600.00")
    assert by_category["Europe"] == Decimal("650.00")


def test_look_through_unknown_category_for_unset_region(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.look_through_service import compute_look_through
    from app.models import PricePoint

    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    stock = client.post(
        "/api/instruments",
        json={
            "name": "No Region Stock", "isin": "XX0000001202",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    db_session.add(
        PricePoint(
            instrument_id=stock, date=date(2024, 1, 1), close=Decimal("50.00"),
            currency="EUR", provider="test", quality="ok",
        )
    )
    db_session.commit()
    client.post(
        "/api/transactions",
        json={
            "external_id": "lt-buy-unk", "date": "2024-01-01", "type": "BUY",
            "account_id": account, "instrument_id": stock,
            "quantity": "2", "price": "50.00", "currency": "EUR",
        },
        headers=auth_headers,
    )

    db = SessionLocal()
    try:
        rows = compute_look_through(db, "region", as_of=date(2024, 1, 1))
    finally:
        db.close()

    assert {r.category: r.value_eur for r in rows} == {"Unknown": Decimal("100.00")}


def test_composition_endpoint_round_trip(client, auth_headers):
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "World ETF", "isin": "XX0000001203",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]

    resp = client.put(
        f"/api/instruments/{instrument}/composition",
        json={"dimension": "region", "breakdown": {"North America": "60", "Europe": "40"}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert {r["category"]: r["weight_pct"] for r in resp.json()} == {
        "North America": "60", "Europe": "40",
    }

    resp = client.get(f"/api/instruments/{instrument}/composition", headers=auth_headers)
    assert len(resp.json()) == 2

    # Re-setting replaces rather than appending.
    resp = client.put(
        f"/api/instruments/{instrument}/composition",
        json={"dimension": "region", "breakdown": {"Asia": "100"}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    resp = client.get(f"/api/instruments/{instrument}/composition", headers=auth_headers)
    assert len(resp.json()) == 1
    assert resp.json()[0]["category"] == "Asia"


def test_composition_endpoint_404s_for_missing_instrument(client, auth_headers):
    """Bug: SQLite FK enforcement is ON, so writing composition for a
    nonexistent instrument used to raise IntegrityError at commit and
    surface as a raw 500 instead of a proper 404."""
    resp = client.put(
        "/api/instruments/999999/composition",
        json={"dimension": "region", "breakdown": {"Asia": "100"}},
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == {
        "code": "instrument_not_found", "params": {"id": 999999},
    }


def test_composition_endpoint_requires_write_scope(client, readonly_headers, auth_headers):
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "World ETF", "isin": "XX0000001204",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    resp = client.put(
        f"/api/instruments/{instrument}/composition",
        json={"dimension": "region", "breakdown": {"Asia": "100"}},
        headers=readonly_headers,
    )
    assert resp.status_code == 403


def test_look_through_endpoint_end_to_end(client, auth_headers, db_session):
    from app.models import PricePoint

    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "World ETF", "isin": "XX0000001205",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    db_session.add(
        PricePoint(
            instrument_id=instrument, date=date(2024, 1, 1), close=Decimal("100.00"),
            currency="EUR", provider="test", quality="ok",
        )
    )
    db_session.commit()
    client.put(
        f"/api/instruments/{instrument}/composition",
        json={"dimension": "region", "breakdown": {"North America": "100"}},
        headers=auth_headers,
    )
    client.post(
        "/api/transactions",
        json={
            "external_id": "lt-endpoint-buy", "date": "2024-01-01", "type": "BUY",
            "account_id": account, "instrument_id": instrument,
            "quantity": "10", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )

    resp = client.get("/api/look-through", params={"dimension": "region"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["dimension"] == "region"
    assert body["rows"] == [{"category": "North America", "value_eur": "1000.00"}]


def test_look_through_endpoint_requires_auth(client):
    resp = client.get("/api/look-through")
    assert resp.status_code == 401
