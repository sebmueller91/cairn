from datetime import date
from decimal import Decimal


def test_position_includes_current_value_and_unrealized_pl(client, auth_headers, db_session):
    from app.models import PricePoint

    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Test ETF",
            "isin": "XX0000000400",
            "asset_class": "EQUITY",
            "valuation_mode": "MARKET",
            "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    client.post(
        "/api/transactions",
        json={
            "external_id": "val-buy-1",
            "date": "2024-01-01",
            "type": "BUY",
            "account_id": account,
            "instrument_id": instrument,
            "quantity": "10",
            "price": "100.00",
            "currency": "EUR",
        },
        headers=auth_headers,
    )
    db_session.add(
        PricePoint(
            instrument_id=instrument,
            date=date(2024, 6, 1),
            close=Decimal("120.00"),
            currency="EUR",
            provider="stooq",
            quality="ok",
        )
    )
    db_session.commit()

    positions = client.get(
        "/api/positions", params={"account_id": account}, headers=auth_headers
    ).json()
    pos = positions[0]
    assert pos["cost_basis_eur"] == "1000.00"
    assert pos["value_eur"] == "1200.00"
    assert pos["unrealized_pl_eur"] == "200.00"


def test_position_value_is_none_without_a_price(client, auth_headers):
    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Test ETF No Price",
            "isin": "XX0000000401",
            "asset_class": "EQUITY",
            "valuation_mode": "MARKET",
            "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    client.post(
        "/api/transactions",
        json={
            "external_id": "val-buy-2",
            "date": "2024-01-01",
            "type": "BUY",
            "account_id": account,
            "instrument_id": instrument,
            "quantity": "5",
            "price": "50.00",
            "currency": "EUR",
        },
        headers=auth_headers,
    )

    positions = client.get(
        "/api/positions", params={"account_id": account}, headers=auth_headers
    ).json()
    assert positions[0]["value_eur"] is None
    assert positions[0]["unrealized_pl_eur"] is None
