"""ADR 0016: standing rules turned into provisional transactions."""

from datetime import date
from decimal import Decimal

from app.models import PricePoint, RecurringBooking, Txn
from app.recurring_service import book_due, nominal_due_date


def _brokerage(client, headers, isin="XX0000001600"):
    account = client.post(
        "/api/accounts",
        json={"name": "Depot", "type": "BROKERAGE", "currency": "EUR"},
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


def _loan_account(client, headers, monthly_payment="800.00"):
    account = client.post(
        "/api/accounts",
        json={"name": "Mortgage", "type": "LOAN", "currency": "EUR"},
        headers=headers,
    ).json()
    resp = client.post(
        "/api/loans",
        json={
            "account_id": account["id"],
            "principal": "100000.00",
            "rate_pct": "2.0",
            "start_date": "2024-01-01",
            "monthly_payment": monthly_payment,
            "payment_day": 31,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.json()
    return account


def _price(db, instrument_id, d, close):
    db.add(
        PricePoint(
            instrument_id=instrument_id,
            date=d,
            close=Decimal(close),
            currency="EUR",
            provider="stooq",
            quality="ok",
        )
    )
    db.commit()


def _rule(client, headers, **fields):
    resp = client.post("/api/recurring-bookings", json=fields, headers=headers)
    assert resp.status_code == 201, resp.json()
    return resp.json()


def _run(db, today):
    result = book_due(db, today=today)
    db.commit()
    return result


def test_nominal_due_date_clamps_to_month_end():
    assert nominal_due_date(31, 2025, 2) == date(2025, 2, 28)
    assert nominal_due_date(31, 2024, 2) == date(2024, 2, 29)
    assert nominal_due_date(31, 2025, 4) == date(2025, 4, 30)
    assert nominal_due_date(2, 2025, 4) == date(2025, 4, 2)


def test_nominal_due_date_counts_back_from_month_end():
    assert nominal_due_date(-1, 2025, 2) == date(2025, 2, 28)
    assert nominal_due_date(-2, 2025, 2) == date(2025, 2, 27)
    assert nominal_due_date(-2, 2024, 2) == date(2024, 2, 28)
    assert nominal_due_date(-2, 2025, 10) == date(2025, 10, 30)


def test_buy_is_provisional_auto_priced_and_cut_to_decimals(client, auth_headers, db_session):
    account, instrument = _brokerage(client, auth_headers)
    _price(db_session, instrument["id"], date(2025, 1, 2), "30.00")
    rule = _rule(
        client,
        auth_headers,
        name="plan",
        type="BUY",
        account_id=account["id"],
        instrument_id=instrument["id"],
        amount_eur="101.00",
        fees="1.00",
        day_of_month=2,
        quantity_decimals=3,
        start_date="2025-01-01",
    )

    result = _run(db_session, date(2025, 1, 15))

    assert result.failures == []
    [txn] = result.booked
    assert txn.external_id == f"recurring-{rule['id']}-2025-01"
    assert txn.date == date(2025, 1, 2)
    assert txn.type.value == "BUY"
    assert txn.provisional is True
    assert txn.price_mode.value == "auto"
    assert txn.price == Decimal("30.00")
    # 100 / 30 = 3.3333... cut, not rounded, to 3 places
    assert txn.quantity == Decimal("3.333")
    assert txn.fees == Decimal("1.00")
    assert txn.amount_eur == Decimal("100.99")
    assert db_session.get(RecurringBooking, rule["id"]).booked_through == date(2025, 1, 2)


def test_second_run_books_nothing(client, auth_headers, db_session):
    account, instrument = _brokerage(client, auth_headers)
    _price(db_session, instrument["id"], date(2025, 1, 2), "30.00")
    _rule(
        client,
        auth_headers,
        name="plan",
        type="BUY",
        account_id=account["id"],
        instrument_id=instrument["id"],
        amount_eur="50.00",
        day_of_month=2,
        start_date="2025-01-01",
    )
    assert len(_run(db_session, date(2025, 1, 15)).booked) == 1
    assert _run(db_session, date(2025, 1, 15)).booked == []
    assert db_session.query(Txn).count() == 1


def test_weekend_shift_and_catch_up(client, auth_headers, db_session):
    account, instrument = _brokerage(client, auth_headers)
    _price(db_session, instrument["id"], date(2025, 1, 31), "20.00")
    _rule(
        client,
        auth_headers,
        name="plan",
        type="BUY",
        account_id=account["id"],
        instrument_id=instrument["id"],
        amount_eur="40.00",
        day_of_month=1,
        start_date="2025-02-01",
    )

    result = _run(db_session, date(2025, 4, 3))

    # 1 Feb and 1 Mar 2025 are Saturdays; 1 Apr is a Tuesday
    assert [t.date for t in result.booked] == [
        date(2025, 2, 3),
        date(2025, 3, 3),
        date(2025, 4, 1),
    ]
    assert len({t.import_batch_id for t in result.booked}) == 1


def test_holiday_shift_waits_for_the_execution_date(client, auth_headers, db_session):
    account, instrument = _brokerage(client, auth_headers)
    _price(db_session, instrument["id"], date(2025, 10, 1), "20.00")
    _rule(
        client,
        auth_headers,
        name="plan",
        type="BUY",
        account_id=account["id"],
        instrument_id=instrument["id"],
        amount_eur="40.00",
        day_of_month=3,
        start_date="2025-10-01",
    )

    # 3 Oct 2025 is a public holiday (Friday) -> executes Monday 6 Oct
    assert _run(db_session, date(2025, 10, 5)).booked == []
    [txn] = _run(db_session, date(2025, 10, 6)).booked
    assert txn.date == date(2025, 10, 6)


def test_end_of_month_rolls_into_next_month(client, auth_headers, db_session):
    account, instrument = _brokerage(client, auth_headers)
    _price(db_session, instrument["id"], date(2025, 5, 30), "20.00")
    rule = _rule(
        client,
        auth_headers,
        name="plan",
        type="BUY",
        account_id=account["id"],
        instrument_id=instrument["id"],
        amount_eur="40.00",
        day_of_month=31,
        start_date="2025-05-01",
    )

    # 31 May 2025 is a Saturday -> executes Monday 2 June
    assert _run(db_session, date(2025, 6, 1)).booked == []
    [txn] = _run(db_session, date(2025, 6, 2)).booked
    assert txn.date == date(2025, 6, 2)
    assert txn.external_id == f"recurring-{rule['id']}-2025-05"


def test_loan_payment_on_second_last_day_without_shift(client, auth_headers, db_session):
    account = _loan_account(client, auth_headers, monthly_payment="800.00")
    rule = _rule(
        client,
        auth_headers,
        name="mortgage",
        type="LOAN_PAYMENT",
        account_id=account["id"],
        day_of_month=-2,
        shift_to_business_day=False,
        start_date="2025-08-01",
    )

    # 30 Aug 2025 is a Saturday, booked on that very day all the same
    assert _run(db_session, date(2025, 8, 29)).booked == []
    [txn] = _run(db_session, date(2025, 8, 30)).booked
    assert txn.type.value == "LOAN_PAYMENT"
    assert txn.date == date(2025, 8, 30)
    assert txn.amount_eur == Decimal("800.00")
    assert txn.external_id == f"recurring-{rule['id']}-2025-08"
    assert txn.provisional is True

    [txn] = _run(db_session, date(2025, 9, 30)).booked
    assert txn.date == date(2025, 9, 29)


def test_missing_price_is_retried_without_skipping_the_month(
    client, auth_headers, db_session
):
    account, instrument = _brokerage(client, auth_headers)
    rule = _rule(
        client,
        auth_headers,
        name="plan",
        type="BUY",
        account_id=account["id"],
        instrument_id=instrument["id"],
        amount_eur="40.00",
        day_of_month=2,
        start_date="2025-01-01",
    )

    result = _run(db_session, date(2025, 1, 15))
    assert result.booked == []
    [failure] = result.failures
    assert failure.code == "no_price_available"
    assert failure.due == date(2025, 1, 2)
    assert db_session.get(RecurringBooking, rule["id"]).booked_through is None

    _price(db_session, instrument["id"], date(2025, 1, 2), "20.00")
    [txn] = _run(db_session, date(2025, 1, 15)).booked
    assert txn.date == date(2025, 1, 2)


def test_deleted_booking_does_not_come_back(client, auth_headers, db_session):
    account, instrument = _brokerage(client, auth_headers)
    _price(db_session, instrument["id"], date(2025, 1, 2), "20.00")
    _rule(
        client,
        auth_headers,
        name="plan",
        type="BUY",
        account_id=account["id"],
        instrument_id=instrument["id"],
        amount_eur="40.00",
        day_of_month=2,
        start_date="2025-01-01",
    )
    [txn] = _run(db_session, date(2025, 1, 15)).booked
    assert client.delete(f"/api/transactions/{txn.id}", headers=auth_headers).status_code == 204

    assert _run(db_session, date(2025, 1, 15)).booked == []


def test_inactive_rules_and_end_date(client, auth_headers, db_session):
    account, instrument = _brokerage(client, auth_headers)
    _price(db_session, instrument["id"], date(2025, 1, 2), "20.00")
    ended = _rule(
        client,
        auth_headers,
        name="ended",
        type="BUY",
        account_id=account["id"],
        instrument_id=instrument["id"],
        amount_eur="40.00",
        day_of_month=2,
        start_date="2025-01-01",
        end_date="2025-02-28",
    )
    paused = _rule(
        client,
        auth_headers,
        name="paused",
        type="BUY",
        account_id=account["id"],
        instrument_id=instrument["id"],
        amount_eur="40.00",
        day_of_month=2,
        start_date="2025-01-01",
    )
    resp = client.patch(
        f"/api/recurring-bookings/{paused['id']}", json={"active": False}, headers=auth_headers
    )
    assert resp.status_code == 200

    booked = _run(db_session, date(2025, 5, 15)).booked
    assert [(t.external_id, t.date) for t in booked] == [
        (f"recurring-{ended['id']}-2025-01", date(2025, 1, 2)),
        (f"recurring-{ended['id']}-2025-02", date(2025, 2, 3)),
    ]


def test_rule_validation(client, auth_headers):
    account, instrument = _brokerage(client, auth_headers)
    loan_account = _loan_account(client, auth_headers)

    def post(**fields):
        body = {"name": "r", "day_of_month": 2, "start_date": "2025-01-01", **fields}
        return client.post("/api/recurring-bookings", json=body, headers=auth_headers)

    resp = post(type="LOAN_PAYMENT", account_id=account["id"])
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "not_a_loan_account"

    resp = post(type="BUY", account_id=account["id"], amount_eur="40.00")
    assert resp.json()["detail"] == {"code": "missing_field", "params": {"field": "instrument_id"}}

    resp = post(
        type="BUY",
        account_id=account["id"],
        instrument_id=instrument["id"],
        amount_eur="5.00",
        fees="5.00",
    )
    assert resp.json()["detail"]["code"] == "fees_exceed_amount"

    resp = post(type="LOAN_PAYMENT", account_id=loan_account["id"], day_of_month=0)
    assert resp.json()["detail"]["code"] == "invalid_day_of_month"

    resp = post(type="DIVIDEND", account_id=account["id"], amount_eur="5.00")
    assert resp.json()["detail"]["code"] == "unsupported_recurring_type"

    resp = post(type="BUY", account_id=loan_account["id"], instrument_id=instrument["id"], amount_eur="5.00")
    assert resp.json()["detail"]["code"] == "loan_account_not_allowed"

    assert post(type="LOAN_PAYMENT", account_id=loan_account["id"]).status_code == 201
    resp = post(type="LOAN_PAYMENT", account_id=loan_account["id"])
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "name_conflict"


def test_readonly_token_cannot_write_rules(client, readonly_headers):
    resp = client.post(
        "/api/recurring-bookings",
        json={"name": "r", "type": "BUY", "account_id": 1, "day_of_month": 2, "start_date": "2025-01-01"},
        headers=readonly_headers,
    )
    assert resp.status_code == 403


def test_run_endpoint_dry_run_writes_nothing(client, auth_headers, db_session):
    account, instrument = _brokerage(client, auth_headers)
    _price(db_session, instrument["id"], date(2025, 1, 2), "20.00")
    rule = _rule(
        client,
        auth_headers,
        name="plan",
        type="BUY",
        account_id=account["id"],
        instrument_id=instrument["id"],
        amount_eur="40.00",
        day_of_month=2,
        start_date="2025-01-01",
        end_date="2025-01-31",
    )

    resp = client.post("/api/recurring-bookings/run?dry_run=true", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert body["import_batch_id"] is None
    assert [t["date"] for t in body["booked"]] == ["2025-01-02"]
    assert client.get("/api/transactions", headers=auth_headers).json() == []
    assert client.get("/api/recurring-bookings", headers=auth_headers).json()[0]["booked_through"] is None

    body = client.post("/api/recurring-bookings/run", headers=auth_headers).json()
    assert body["import_batch_id"] is not None
    assert len(client.get("/api/transactions", headers=auth_headers).json()) == 1
    assert client.get("/api/recurring-bookings", headers=auth_headers).json()[0][
        "booked_through"
    ] == "2025-01-02"
    assert rule["booked_through"] is None
