"""spec 4.1: investable / gross / net must stay distinguishable
everywhere. Invented figures only."""

from datetime import date
from decimal import Decimal


def test_house_and_loan_flow_into_gross_and_net(client, auth_headers, db_session):
    from app.snapshot_service import rebuild_snapshots
    from app.models import DailySnapshot

    house_account = client.post(
        "/api/accounts",
        json={"name": "Home", "type": "REAL_ESTATE", "currency": "EUR"},
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
    # OPENING_BALANCE establishes the position (quantity=1) the snapshot
    # engine values day by day.
    client.post(
        "/api/transactions",
        json={
            "external_id": "house-opening-1",
            "date": "2024-01-01",
            "type": "OPENING_BALANCE",
            "account_id": house_account["id"],
            "instrument_id": house["id"],
            "quantity": "1",
            "amount": "400000.00",
            "currency": "EUR",
            "provisional": False,
        },
        headers=auth_headers,
    )
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

    loan_account = client.post(
        "/api/accounts",
        json={"name": "Mortgage", "type": "LOAN", "currency": "EUR"},
        headers=auth_headers,
    ).json()
    client.post(
        "/api/loans",
        json={
            "account_id": loan_account["id"],
            "principal": "300000.00",
            "rate_pct": "3.0",
            "start_date": "2024-01-01",
            "monthly_payment": "1500.00",
        },
        headers=auth_headers,
    )

    rebuild_snapshots(db_session)

    def total(scope_id, day):
        row = (
            db_session.query(DailySnapshot)
            .filter(
                DailySnapshot.date == day,
                DailySnapshot.scope_type == "total",
                DailySnapshot.scope_id == scope_id,
            )
            .first()
        )
        return row.value_eur if row else None

    day = date(2024, 1, 1)
    investable = total("investable", day)
    gross = total("gross", day)
    net = total("net", day)

    assert investable == Decimal("0.00")  # no securities/cash booked
    assert gross == Decimal("400000.00")  # investable + house
    assert net == Decimal("100000.00")  # gross - loan principal (300000, day 0)

    loan_row = (
        db_session.query(DailySnapshot)
        .filter(
            DailySnapshot.date == day,
            DailySnapshot.scope_type == "loan",
        )
        .first()
    )
    assert loan_row.value_eur == Decimal("-300000.00")  # a liability, stored negative


def test_networth_timeseries_scope_parameter(client, auth_headers, db_session):
    from app.models import DailySnapshot

    for scope in ("investable", "gross", "net"):
        db_session.add(
            DailySnapshot(
                date=date(2024, 1, 1),
                scope_type="total",
                scope_id=scope,
                value_eur=Decimal("100.00") if scope == "investable" else Decimal("200.00"),
            )
        )
    db_session.commit()

    investable = client.get(
        "/api/timeseries/networth", params={"scope": "investable"}, headers=auth_headers
    ).json()
    net = client.get(
        "/api/timeseries/networth", params={"scope": "net"}, headers=auth_headers
    ).json()
    assert investable[0]["value_eur"] == "100.00"
    assert net[0]["value_eur"] == "200.00"
