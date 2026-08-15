from datetime import date
from decimal import Decimal


def test_delete_loan(client, auth_headers):
    loan_account = client.post(
        "/api/accounts",
        json={"name": "Mortgage", "type": "LOAN", "currency": "EUR"},
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

    resp = client.delete(f"/api/loans/{loan['id']}", headers=auth_headers)
    assert resp.status_code == 204
    assert client.get(f"/api/loans/{loan['id']}", headers=auth_headers).status_code == 404


def test_create_loan_requires_a_loan_account(client, auth_headers):
    brokerage = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()

    resp = client.post(
        "/api/loans",
        json={
            "account_id": brokerage["id"],
            "principal": "300000.00",
            "rate_pct": "3.5",
            "start_date": "2024-01-01",
            "monthly_payment": "1500.00",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "not_a_loan_account"


def test_loan_status_reports_balance_and_ltv(client, auth_headers, db_session):
    loan_account = client.post(
        "/api/accounts",
        json={"name": "Mortgage", "type": "LOAN", "currency": "EUR"},
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

    house = client.post(
        "/api/instruments",
        json={
            "name": "Test House",
            "asset_class": "REAL_ESTATE",
            "valuation_mode": "ANCHORED",
            "currency": "EUR",
        },
        headers=auth_headers,
    ).json()
    client.post(
        "/api/valuations",
        json={
            "instrument_id": house["id"],
            "date": "2024-01-01",
            "value_eur": "400000.00",
            "method": "purchase",
        },
        headers=auth_headers,
    )

    status_resp = client.get(
        f"/api/loans/{loan['id']}/status",
        params={"as_of": "2024-02-01", "house_instrument_id": house["id"]},
        headers=auth_headers,
    )
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["balance_eur"] == "99500.00"  # matches test_loan_service golden number
    assert body["house_value_eur"] == "400000.00"  # no index configured -> flat anchor
    assert body["ltv"] == "0.24875"  # 99500/400000


def test_extra_repayment_reduces_reported_balance(client, auth_headers):
    loan_account = client.post(
        "/api/accounts",
        json={"name": "Mortgage", "type": "LOAN", "currency": "EUR"},
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

    client.post(
        "/api/transactions",
        json={
            "external_id": "extra-repay-1",
            "date": "2024-01-15",
            "type": "EXTRA_REPAYMENT",
            "account_id": loan_account["id"],
            "amount": "5000.00",
            "currency": "EUR",
        },
        headers=auth_headers,
    )

    status_resp = client.get(
        f"/api/loans/{loan['id']}/status",
        params={"as_of": "2024-02-01"},
        headers=auth_headers,
    )
    assert status_resp.json()["balance_eur"] == "94500.00"


def test_loan_payment_requires_loan_account(client, auth_headers):
    brokerage = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()
    resp = client.post(
        "/api/transactions",
        json={
            "external_id": "bad-loan-payment",
            "date": "2024-01-15",
            "type": "LOAN_PAYMENT",
            "account_id": brokerage["id"],
            "amount": "1000.00",
            "currency": "EUR",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "not_a_loan_account"
