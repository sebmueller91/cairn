"""Invented amounts only, per AGENTS.md."""

import math
from datetime import date
from decimal import Decimal

import pytest

from app.milestones_service import (
    compute_milestone,
    months_to_reach,
    next_round_number,
    trailing_12mo_savings_rate,
)


def test_next_round_number_hand_derived():
    assert next_round_number(Decimal(127450)) == Decimal(200000)
    assert next_round_number(Decimal(45)) == Decimal(50)
    assert next_round_number(Decimal(999)) == Decimal(1000)
    assert next_round_number(Decimal(100000)) == Decimal(200000)  # not "strictly greater"
    assert next_round_number(Decimal(0)) == Decimal(1000)
    assert next_round_number(Decimal(-500)) == Decimal(1000)


def test_months_to_reach_zero_return_with_savings():
    # (2000 - 1000) / 100 per month = 10 months exactly.
    assert months_to_reach(Decimal(1000), Decimal(2000), Decimal(100), Decimal(0)) == 10.0


def test_months_to_reach_zero_return_no_savings_is_unreachable():
    assert months_to_reach(Decimal(1000), Decimal(2000), Decimal(0), Decimal(0)) is None


def test_months_to_reach_already_at_target():
    assert months_to_reach(Decimal(2000), Decimal(1000), Decimal(0), Decimal(0)) == 0.0


def test_months_to_reach_pure_compounding_matches_the_growth_equation():
    # No monthly savings, just letting 1000 compound at 12%/yr (1%/mo)
    # to 2000 -> verify the closed-form growth equation holds at the
    # solved month count, the same "check the equation" pattern used for
    # XIRR rather than trusting a separately hand-derived number.
    months = months_to_reach(Decimal(1000), Decimal(2000), Decimal(0), Decimal(12))
    assert months is not None
    grown = 1000 * (1.01**months)
    assert grown == pytest.approx(2000.0, rel=1e-6)
    assert months == pytest.approx(math.log(2) / math.log(1.01), rel=1e-9)


def test_trailing_12mo_savings_rate_hand_derived(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.models import PricePoint

    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Test ETF", "isin": "XX0000001300",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    db_session.add(
        PricePoint(
            instrument_id=instrument, date=date(2024, 6, 1), close=Decimal("100.00"),
            currency="EUR", provider="test", quality="ok",
        )
    )
    db_session.commit()
    # A single BUY of 1200 within the trailing 12mo window.
    client.post(
        "/api/transactions",
        json={
            "external_id": "ms-buy-1", "date": "2024-06-01", "type": "BUY",
            "account_id": account, "instrument_id": instrument,
            "quantity": "12", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )

    db = SessionLocal()
    try:
        rate = trailing_12mo_savings_rate(db, as_of=date(2025, 1, 1))
    finally:
        db.close()

    # 1200 total flow over 12 months = 100/month.
    assert rate == Decimal("100.00")


def test_compute_milestone_end_to_end(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.models import DailySnapshot

    db_session.add(
        DailySnapshot(
            date=date(2025, 1, 1), scope_type="total", scope_id="net",
            value_eur=Decimal("127450.00"),
        )
    )
    db_session.commit()

    db = SessionLocal()
    try:
        result = compute_milestone(
            db, scope="net", assumed_annual_return_pct=Decimal(5), as_of=date(2025, 1, 1)
        )
    finally:
        db.close()

    assert result.current_value_eur == Decimal("127450.00")
    assert result.next_milestone_eur == Decimal(200000)
    assert result.months_to_reach is not None
    assert result.estimated_date is not None
    assert result.estimated_date > date(2025, 1, 1)


def test_milestones_endpoint_end_to_end(client, auth_headers, db_session):
    from app.models import DailySnapshot

    db_session.add(
        DailySnapshot(
            date=date.today(), scope_type="total", scope_id="net",
            value_eur=Decimal("50000.00"),
        )
    )
    db_session.commit()

    resp = client.get("/api/milestones", params={"scope": "net"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_value_eur"] == "50000.00"
    assert body["next_milestone_eur"] == "100000"


def test_milestones_endpoint_requires_auth(client):
    resp = client.get("/api/milestones")
    assert resp.status_code == 401
