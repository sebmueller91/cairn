"""One global `known_deposits` list must not leak across cash accounts.

`rebuild_snapshots` derives portfolio deposits once (money that left *some*
cash account and funded a BUY) and, before this fix, handed the identical
list to every CASH account's interpolation — so a withdrawal that only
happened in account A also got "explained away" in account B, which never
saw a cent of it. B's daily balance would visibly swing up and back down
around the deposit date even though its own statements never moved.

The data model has no field recording which specific cash account funded a
given derived deposit (spec 3.6: "for a portfolio, a deposit is always
external regardless of which account it came from") — there is genuinely
no way to attribute it with certainty when more than one cash account
exists. The fix therefore only applies deposit-aware interpolation when
there is exactly one CASH account (the unambiguous case); with more than
one it withholds the correction rather than guessing. This test's
un-involved account B is the thing that must stop being corrupted; see
the report for the accepted trade-off on the true funding account.

Invented amounts only, per AGENTS.md.
"""

from datetime import date
from decimal import Decimal

from app.models import DailySnapshot
from app.snapshot_service import rebuild_snapshots


def _account(client, headers, name, type_):
    return client.post(
        "/api/accounts",
        json={"name": name, "type": type_, "currency": "EUR"},
        headers=headers,
    ).json()["id"]


def _instrument(client, headers, isin):
    return client.post(
        "/api/instruments",
        json={
            "name": "Test ETF", "isin": isin, "asset_class": "EQUITY",
            "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=headers,
    ).json()["id"]


def _statement(client, headers, ext, account, day, amount):
    resp = client.post(
        "/api/transactions",
        json={
            "external_id": ext, "date": day, "type": "BALANCE_STATEMENT",
            "account_id": account, "amount": amount, "currency": "EUR",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text


def _cash_series(db_session, account_id):
    rows = (
        db_session.query(DailySnapshot)
        .filter(
            DailySnapshot.scope_type == "cash_account",
            DailySnapshot.scope_id == str(account_id),
        )
        .order_by(DailySnapshot.date)
        .all()
    )
    return {r.date: r.value_eur for r in rows}


def test_a_deposit_funded_from_one_cash_account_does_not_leak_into_another(
    client, auth_headers, db_session
):
    account_a = _account(client, auth_headers, "Girokonto A", "CASH")
    account_b = _account(client, auth_headers, "Girokonto B", "CASH")
    portfolio = _account(client, auth_headers, "Depot", "BROKERAGE")
    instrument = _instrument(client, auth_headers, "XX0000009101")

    # Account A funds a portfolio purchase mid-window: 10,000 -> 5,000.
    _statement(client, auth_headers, "a-1", account_a, "2024-01-01", "10000.00")
    _statement(client, auth_headers, "a-2", account_a, "2024-01-11", "5000.00")

    # Account B is untouched the whole time: flat 3,000 in, flat 3,000 out.
    _statement(client, auth_headers, "b-1", account_b, "2024-01-01", "3000.00")
    _statement(client, auth_headers, "b-2", account_b, "2024-01-11", "3000.00")

    # The BUY that (per spec 3.6) auto-derives a 5,000 external deposit on
    # 2024-01-06 for the portfolio account — the settlement balance goes
    # from 0 to -5000, booked as a deposit and reset to 0.
    resp = client.post(
        "/api/transactions",
        json={
            "external_id": "buy-1", "date": "2024-01-06", "type": "BUY",
            "account_id": portfolio, "instrument_id": instrument,
            "quantity": "50", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text

    rebuild_snapshots(db_session)

    series_b = _cash_series(db_session, account_b)
    # Account B never funded anything: every day in the window must read
    # its own flat, unexplained 3,000 — not a phantom swing borrowed from
    # account A's withdrawal.
    for d in (
        date(2024, 1, 1), date(2024, 1, 3), date(2024, 1, 5),
        date(2024, 1, 6), date(2024, 1, 8), date(2024, 1, 11),
    ):
        assert series_b[d] == Decimal("3000.00"), f"{d}: {series_b[d]}"

    series_a = _cash_series(db_session, account_a)
    assert series_a[date(2024, 1, 1)] == Decimal("10000.00")
    assert series_a[date(2024, 1, 11)] == Decimal("5000.00")
