from datetime import date
from decimal import Decimal


def _create_account(client, headers, name="Portfolio A", type_="BROKERAGE"):
    return client.post(
        "/api/accounts",
        json={"name": name, "type": type_, "currency": "EUR"},
        headers=headers,
    ).json()["id"]


def _create_instrument(client, headers, isin="XX0000000200"):
    return client.post(
        "/api/instruments",
        json={
            "name": "Test ETF",
            "isin": isin,
            "asset_class": "EQUITY",
            "valuation_mode": "MARKET",
            "currency": "EUR",
        },
        headers=headers,
    ).json()["id"]


def test_rebuild_values_a_market_position_with_carry_forward_price(
    client, auth_headers, db_session
):
    from app.models import PricePoint
    from app.snapshot_service import rebuild_snapshots

    account = _create_account(client, auth_headers)
    instrument = _create_instrument(client, auth_headers)

    client.post(
        "/api/transactions",
        json={
            "external_id": "snap-buy-1",
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
            date=date(2024, 1, 1),
            close=Decimal("100.00"),
            currency="EUR",
            provider="stooq",
            quality="ok",
        )
    )
    db_session.add(
        PricePoint(
            instrument_id=instrument,
            date=date(2024, 1, 5),
            close=Decimal("110.00"),
            currency="EUR",
            provider="stooq",
            quality="ok",
        )
    )
    db_session.commit()

    days = rebuild_snapshots(db_session)
    assert days > 0

    from app.models import DailySnapshot

    def value_on(d):
        row = (
            db_session.query(DailySnapshot)
            .filter(
                DailySnapshot.date == d,
                DailySnapshot.scope_type == "position",
                DailySnapshot.scope_id == f"{account}:{instrument}",
            )
            .first()
        )
        return row.value_eur if row else None

    assert value_on(date(2024, 1, 1)) == Decimal("1000.00")
    # 2024-01-03 has no price of its own -> carries forward 2024-01-01's 100
    assert value_on(date(2024, 1, 3)) == Decimal("1000.00")
    assert value_on(date(2024, 1, 5)) == Decimal("1100.00")

    total = (
        db_session.query(DailySnapshot)
        .filter(
            DailySnapshot.date == date(2024, 1, 5),
            DailySnapshot.scope_type == "total",
            DailySnapshot.scope_id == "investable",
        )
        .first()
    )
    assert total.value_eur == Decimal("1100.00")


def test_rebuild_includes_cash_account_balance(client, auth_headers, db_session):
    from app.snapshot_service import rebuild_snapshots

    cash_account = _create_account(client, auth_headers, name="Girokonto", type_="CASH")

    for ext_id, day, balance in [
        ("bal-1", "2024-01-01", "500.00"),
        ("bal-2", "2024-01-11", "700.00"),
    ]:
        client.post(
            "/api/transactions",
            json={
                "external_id": ext_id,
                "date": day,
                "type": "BALANCE_STATEMENT",
                "account_id": cash_account,
                "amount": balance,
                "currency": "EUR",
            },
            headers=auth_headers,
        )

    rebuild_snapshots(db_session)

    from app.models import DailySnapshot

    mid = (
        db_session.query(DailySnapshot)
        .filter(
            DailySnapshot.date == date(2024, 1, 6),
            DailySnapshot.scope_type == "cash_account",
            DailySnapshot.scope_id == str(cash_account),
        )
        .first()
    )
    assert mid.value_eur == Decimal("600.00")  # halfway between 500 and 700, no deposits

    total = (
        db_session.query(DailySnapshot)
        .filter(
            DailySnapshot.date == date(2024, 1, 6),
            DailySnapshot.scope_type == "total",
            DailySnapshot.scope_id == "investable",
        )
        .first()
    )
    assert total.value_eur == Decimal("600.00")


def test_rebuild_is_idempotent_and_wipes_stale_rows(client, auth_headers, db_session):
    from app.models import DailySnapshot
    from app.snapshot_service import rebuild_snapshots

    account = _create_account(client, auth_headers)
    instrument = _create_instrument(client, auth_headers, isin="XX0000000201")
    client.post(
        "/api/transactions",
        json={
            "external_id": "snap-buy-2",
            "date": "2024-01-01",
            "type": "BUY",
            "account_id": account,
            "instrument_id": instrument,
            "quantity": "1",
            "price": "10.00",
            "currency": "EUR",
        },
        headers=auth_headers,
    )
    rebuild_snapshots(db_session)
    first_count = db_session.query(DailySnapshot).count()

    rebuild_snapshots(db_session)
    second_count = db_session.query(DailySnapshot).count()

    assert first_count == second_count
    assert first_count > 0


def test_cash_balance_carries_forward_past_the_last_statement(
    client, auth_headers, db_session
):
    """The day after the last statement must not read as a balance of zero.

    Nothing refreshes a cash account the way a price feed refreshes an
    instrument, so the absence of a newer statement is the normal state,
    not a signal that the money is gone. Before this, the account simply
    stopped being written and its whole balance dropped out of net worth
    overnight — silently, because a missing snapshot row and a genuine
    zero are indistinguishable downstream.
    """
    from app.models import DailySnapshot
    from app.snapshot_service import rebuild_snapshots

    cash_account = _create_account(client, auth_headers, name="Giro", type_="CASH")
    client.post(
        "/api/transactions",
        json={
            "external_id": "carry-bal-1",
            "date": "2024-03-01",
            "type": "BALANCE_STATEMENT",
            "account_id": cash_account,
            "amount": "4200.00",
            "currency": "EUR",
        },
        headers=auth_headers,
    )

    rebuild_snapshots(db_session)

    def cash_on(d):
        row = (
            db_session.query(DailySnapshot)
            .filter(
                DailySnapshot.date == d,
                DailySnapshot.scope_type == "cash_account",
                DailySnapshot.scope_id == str(cash_account),
            )
            .first()
        )
        return row.value_eur if row else None

    assert cash_on(date(2024, 3, 1)) == Decimal("4200.00")
    assert cash_on(date(2024, 3, 2)) == Decimal("4200.00")
    assert cash_on(date.today()) == Decimal("4200.00")
    # ...but only forward. A date before the account had any statement is
    # unknown, not 4200, and must stay absent.
    assert cash_on(date(2024, 2, 28)) is None

    total = (
        db_session.query(DailySnapshot)
        .filter(
            DailySnapshot.date == date.today(),
            DailySnapshot.scope_type == "total",
            DailySnapshot.scope_id == "investable",
        )
        .first()
    )
    assert total.value_eur == Decimal("4200.00")
