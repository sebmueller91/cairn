"""Invented ISINs and quantities only, per AGENTS.md."""

from datetime import date, timedelta
from decimal import Decimal


def test_no_issues_for_a_freshly_priced_position(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.data_quality_service import check_data_quality
    from app.models import PricePoint

    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Fresh ETF", "isin": "XX0000000900",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    today = date.today()
    db_session.add(
        PricePoint(
            instrument_id=instrument, date=today, close=Decimal("100.00"),
            currency="EUR", provider="test", quality="ok",
        )
    )
    db_session.commit()
    client.post(
        "/api/transactions",
        json={
            "external_id": "dq-buy-1", "date": str(today), "type": "BUY",
            "account_id": account, "instrument_id": instrument,
            "quantity": "1", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )

    db = SessionLocal()
    try:
        issues = check_data_quality(db, as_of=today)
    finally:
        db.close()
    assert [i for i in issues if i.instrument_id == instrument] == []


def test_stale_price_is_flagged(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.data_quality_service import check_data_quality
    from app.models import PricePoint

    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Stale ETF", "isin": "XX0000000901",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    old_date = date(2024, 1, 1)
    db_session.add(
        PricePoint(
            instrument_id=instrument, date=old_date, close=Decimal("100.00"),
            currency="EUR", provider="test", quality="ok",
        )
    )
    db_session.commit()
    client.post(
        "/api/transactions",
        json={
            "external_id": "dq-buy-2", "date": str(old_date), "type": "BUY",
            "account_id": account, "instrument_id": instrument,
            "quantity": "1", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )

    as_of = old_date + timedelta(days=30)
    db = SessionLocal()
    try:
        issues = check_data_quality(db, as_of=as_of)
    finally:
        db.close()
    matches = [i for i in issues if i.instrument_id == instrument]
    assert len(matches) == 1
    assert matches[0].kind == "stale_price"
    assert matches[0].age_days == 30


def test_missing_price_is_flagged(client, auth_headers):
    from app.database import SessionLocal
    from app.data_quality_service import check_data_quality

    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "No Price ETF", "isin": "XX0000000902",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    client.post(
        "/api/transactions",
        json={
            "external_id": "dq-buy-3", "date": "2024-01-01", "type": "BUY",
            "account_id": account, "instrument_id": instrument,
            "quantity": "1", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )

    db = SessionLocal()
    try:
        issues = check_data_quality(db)
    finally:
        db.close()
    matches = [i for i in issues if i.instrument_id == instrument]
    assert len(matches) == 1
    assert matches[0].kind == "missing_price"


def test_zero_cost_basis_position_is_flagged(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.data_quality_service import check_data_quality
    from app.models import PricePoint

    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Gifted Shares", "isin": "XX0000000903",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    today = date.today()
    db_session.add(
        PricePoint(
            instrument_id=instrument, date=today, close=Decimal("50.00"),
            currency="EUR", provider="test", quality="ok",
        )
    )
    db_session.commit()
    # A gift/grant booked at zero cost — a real, if unusual, scenario.
    client.post(
        "/api/transactions",
        json={
            "external_id": "dq-buy-4", "date": str(today), "type": "BUY",
            "account_id": account, "instrument_id": instrument,
            "quantity": "5", "price": "0.00", "currency": "EUR",
        },
        headers=auth_headers,
    )

    db = SessionLocal()
    try:
        issues = check_data_quality(db, as_of=today)
    finally:
        db.close()
    kinds = {i.kind for i in issues if i.instrument_id == instrument}
    assert "no_cost_basis" in kinds


def test_stale_house_valuation_is_flagged(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.data_quality_service import check_data_quality
    from app.models import ValuationAnchor

    house_account = client.post(
        "/api/accounts",
        json={"name": "Home", "type": "REAL_ESTATE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    house = client.post(
        "/api/instruments",
        json={
            "name": "Old House", "asset_class": "REAL_ESTATE",
            "valuation_mode": "ANCHORED", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    anchor_date = date(2020, 1, 1)
    db_session.add(
        ValuationAnchor(
            instrument_id=house, date=anchor_date, value_eur=Decimal("300000.00"),
            method="purchase",
        )
    )
    db_session.commit()
    client.post(
        "/api/transactions",
        json={
            "external_id": "dq-house-1", "date": str(anchor_date), "type": "OPENING_BALANCE",
            "account_id": house_account, "instrument_id": house,
            "quantity": "1", "amount": "300000.00", "currency": "EUR", "provisional": False,
        },
        headers=auth_headers,
    )

    as_of = anchor_date + timedelta(days=800)  # well past the 2-year threshold
    db = SessionLocal()
    try:
        issues = check_data_quality(db, as_of=as_of)
    finally:
        db.close()
    matches = [i for i in issues if i.instrument_id == house]
    assert len(matches) == 1
    assert matches[0].kind == "stale_valuation"


def test_data_quality_endpoint_end_to_end(client, auth_headers):
    resp = client.get("/api/data-quality", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"issues": []}


def test_data_quality_endpoint_requires_auth(client):
    resp = client.get("/api/data-quality")
    assert resp.status_code == 401
