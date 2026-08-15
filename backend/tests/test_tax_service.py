"""Invented ISINs, quantities, and amounts only, per AGENTS.md."""

from datetime import date
from decimal import Decimal


def _setup(client, auth_headers, db_session):
    from app.models import PricePoint

    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Test ETF", "isin": "XX0000001100",
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
    client.post(
        "/api/transactions",
        json={
            "external_id": "tax-buy-1", "date": "2024-01-01", "type": "BUY",
            "account_id": account, "instrument_id": instrument,
            "quantity": "10", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    client.post(
        "/api/transactions",
        json={
            "external_id": "tax-sell-1", "date": "2024-06-01", "type": "SELL",
            "account_id": account, "instrument_id": instrument,
            "quantity": "5", "price": "120.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    return account, instrument


def test_realized_gains_fifo_hand_derived(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.tax_service import realized_gains

    _setup(client, auth_headers, db_session)

    db = SessionLocal()
    try:
        gains = realized_gains(db)
    finally:
        db.close()

    # Sold 5 @ 120 = 600 proceeds; cost of those 5 units @ 100 = 500 -> gain 100.
    assert len(gains) == 1
    assert gains[0].date == date(2024, 6, 1)
    assert gains[0].gain_eur == Decimal("100.00")


def test_saver_allowance_usage_hand_derived(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.tax_service import saver_allowance_usage

    account, instrument = _setup(client, auth_headers, db_session)
    client.post(
        "/api/transactions",
        json={
            "external_id": "tax-div-1", "date": "2024-07-01", "type": "DIVIDEND",
            "account_id": account, "instrument_id": instrument,
            "amount": "50.00", "currency": "EUR",
        },
        headers=auth_headers,
    )

    db = SessionLocal()
    try:
        usage = saver_allowance_usage(db, 2024, Decimal(1000))
    finally:
        db.close()

    assert usage["realized_gains_eur"] == Decimal("100.00")
    assert usage["investment_income_eur"] == Decimal("50.00")
    assert usage["total_eur"] == Decimal("150.00")
    assert usage["remaining_eur"] == Decimal("850.00")


def test_saver_allowance_usage_only_counts_the_given_year(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.tax_service import saver_allowance_usage

    _setup(client, auth_headers, db_session)  # sell is dated 2024-06-01

    db = SessionLocal()
    try:
        usage = saver_allowance_usage(db, 2025, Decimal(1000))
    finally:
        db.close()

    assert usage["realized_gains_eur"] == Decimal(0)
    assert usage["total_eur"] == Decimal(0)


def test_unrealized_tax_estimate_hand_derived(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.models import PricePoint
    from app.tax_service import unrealized_tax_estimates

    account, instrument = _setup(client, auth_headers, db_session)
    # Remaining position after the sell: 5 units, cost basis 500. Mark
    # the price up to 150 -> current value 750, unrealized = 250.
    db_session.add(
        PricePoint(
            instrument_id=instrument, date=date(2024, 12, 1), close=Decimal("150.00"),
            currency="EUR", provider="test", quality="ok",
        )
    )
    db_session.commit()

    db = SessionLocal()
    try:
        rows_no_allowance = unrealized_tax_estimates(
            db, remaining_allowance_eur=Decimal(0), as_of=date(2024, 12, 15)
        )
        rows_with_allowance = unrealized_tax_estimates(
            db, remaining_allowance_eur=Decimal(600), as_of=date(2024, 12, 15)
        )
    finally:
        db.close()

    assert len(rows_no_allowance) == 1
    row = rows_no_allowance[0]
    assert row.quantity == Decimal("5")
    assert row.cost_basis_eur == Decimal("500.00")
    assert row.current_value_eur == Decimal("750.00")
    assert row.unrealized_pl_eur == Decimal("250.00")
    # 250 * 0.25 * 1.055 = 65.9375
    assert row.estimated_tax_eur == Decimal("250.00") * Decimal("0.25") * Decimal("1.055")

    # Allowance headroom (600) covers the whole 250 gain -> no tax.
    assert rows_with_allowance[0].estimated_tax_eur == Decimal(0)


def test_vorabpauschale_reminder_only_in_january_with_holdings(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.tax_service import vorabpauschale_reminder

    _setup(client, auth_headers, db_session)

    db = SessionLocal()
    try:
        january = vorabpauschale_reminder(db, as_of=date(2025, 1, 15))
        june = vorabpauschale_reminder(db, as_of=date(2025, 6, 15))
    finally:
        db.close()

    assert january is not None
    assert "Test ETF" in january
    assert june is None


def test_vorabpauschale_reminder_none_without_holdings(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.tax_service import vorabpauschale_reminder

    db = SessionLocal()
    try:
        result = vorabpauschale_reminder(db, as_of=date(2025, 1, 15))
    finally:
        db.close()

    assert result is None


def test_tax_overview_endpoint_end_to_end(client, auth_headers, db_session):
    from app.models import PricePoint

    account, instrument = _setup(client, auth_headers, db_session)
    db_session.add(
        PricePoint(
            instrument_id=instrument, date=date(2024, 12, 1), close=Decimal("150.00"),
            currency="EUR", provider="test", quality="ok",
        )
    )
    db_session.commit()

    resp = client.get(
        "/api/tax", params={"year": 2024, "allowance": "1000"}, headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["saver_allowance"]["realized_gains_eur"] == "100.00"
    assert len(body["unrealized"]) == 1
    assert body["unrealized"][0]["unrealized_pl_eur"] == "250.00"
    assert body["vorabpauschale_reminder"] is None  # default "today" isn't January


def test_tax_overview_endpoint_requires_auth(client):
    resp = client.get("/api/tax")
    assert resp.status_code == 401
