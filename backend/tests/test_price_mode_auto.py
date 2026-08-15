"""spec 2.5: 'a purchase with an unknown price is still bookable ... with
auto, the app takes the price from its own price history at the date.'"""

from datetime import date
from decimal import Decimal


def _setup(client, headers, isin="XX0000000700"):
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
    return account, instrument


def test_auto_price_mode_uses_price_history(client, auth_headers, db_session):
    from app.models import PricePoint

    account, instrument = _setup(client, auth_headers)
    db_session.add(
        PricePoint(
            instrument_id=instrument["id"],
            date=date(2024, 6, 1),
            close=Decimal("95.50"),
            currency="EUR",
            provider="stooq",
            quality="ok",
        )
    )
    db_session.commit()

    resp = client.post(
        "/api/transactions",
        json={
            "external_id": "auto-buy-1",
            "date": "2024-06-15",  # after the price point -> carries forward
            "type": "BUY",
            "account_id": account["id"],
            "instrument_id": instrument["id"],
            "quantity": "10",
            "price_mode": "auto",
            "currency": "EUR",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["price"] == "95.50"
    assert body["price_mode"] == "auto"
    assert body["amount_eur"] == "955.00"


def test_auto_price_mode_without_any_history_is_a_clear_error(client, auth_headers):
    account, instrument = _setup(client, auth_headers, isin="XX0000000701")

    resp = client.post(
        "/api/transactions",
        json={
            "external_id": "auto-buy-2",
            "date": "2024-06-15",
            "type": "BUY",
            "account_id": account["id"],
            "instrument_id": instrument["id"],
            "quantity": "10",
            "price_mode": "auto",
            "currency": "EUR",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "no_price_available"


def test_explicit_price_wins_over_auto_lookup(client, auth_headers, db_session):
    from app.models import PricePoint

    account, instrument = _setup(client, auth_headers, isin="XX0000000702")
    db_session.add(
        PricePoint(
            instrument_id=instrument["id"],
            date=date(2024, 6, 1),
            close=Decimal("95.50"),
            currency="EUR",
            provider="stooq",
            quality="ok",
        )
    )
    db_session.commit()

    resp = client.post(
        "/api/transactions",
        json={
            "external_id": "auto-buy-3",
            "date": "2024-06-15",
            "type": "BUY",
            "account_id": account["id"],
            "instrument_id": instrument["id"],
            "quantity": "10",
            "price": "100.00",  # exact, printed on a statement
            "price_mode": "exact",
            "currency": "EUR",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["price"] == "100.00"
