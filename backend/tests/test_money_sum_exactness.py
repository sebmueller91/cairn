"""Money must never round-trip through SQLite's SUM().

SQLite has no decimal aggregate: func.sum() over a Money (TEXT) column
casts every row to REAL and adds in binary floating point. The Money
TypeDecorator's result processor then does Decimal(that_float) — which
reproduces the float's exact binary noise (e.g.
3940.0399999999999636202119290828704833984375) rather than cleaning it
up, because Decimal(a_float) is exact-by-construction, not
str()-rounded. A later `Decimal(str(...))` on the *already-Decimal*
result is a no-op: str(Decimal) prints full precision, unlike str(float)
which prints the shortest round-tripping form.

The corruption is data-dependent: sums that happen to land on a
binary-exact float slip through clean. 10.10 + 20.20 + 30.30 does not —
verified directly against sqlite3 in the investigation for this fix, it
lands on 60.60000000000000142108547152020037174224853515625 through
SQL SUM(), against the true 60.60.

Invented amounts only, per AGENTS.md.
"""

from datetime import date
from decimal import Decimal

from app.contributions_service import _total_on, compute_contributions
from app.models import DailySnapshot


def _account(client, headers, name, type_="BROKERAGE"):
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


def _buy(client, headers, ext, account, instrument, day, qty, price):
    resp = client.post(
        "/api/transactions",
        json={
            "external_id": ext, "date": day, "type": "BUY",
            "account_id": account, "instrument_id": instrument,
            "quantity": qty, "price": price, "currency": "EUR",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp


def test_contributions_txn_amount_sum_is_exact_not_float_derived(
    client, auth_headers, db_session
):
    """Three BUYs whose amounts are not binary-exact must sum to exactly
    60.60 — not a Decimal carrying float noise."""
    account = _account(client, auth_headers, "Depot")
    instrument = _instrument(client, auth_headers, "XX0000009001")

    # quantity 1 x price P => amount_eur == P, so each BUY's amount_eur is
    # exactly 10.10 / 20.20 / 30.30 — the same trio that visibly diverges
    # through SQLite SUM() (see module docstring).
    _buy(client, auth_headers, "sum-1", account, instrument, "2025-01-01", "1", "10.10")
    _buy(client, auth_headers, "sum-2", account, instrument, "2025-01-02", "1", "20.20")
    _buy(client, auth_headers, "sum-3", account, instrument, "2025-01-03", "1", "30.30")

    result = compute_contributions(db_session, date(2024, 12, 31), date(2025, 12, 31))

    total = result.by_asset_class["EQUITY"]
    assert total == Decimal("60.60")
    # Not merely equal in value — exactly two decimal places, no leftover
    # binary-float mantissa hiding behind Decimal equality.
    assert str(total) == "60.60"
    assert result.total_invested == Decimal("60.60")


def test_total_on_snapshot_sum_is_exact_not_float_derived(db_session):
    """_total_on sums multiple same-date rows (the `loan` scope: one row
    per loan) via DailySnapshot.value_eur — also money, also must not
    touch func.sum()."""
    db_session.add(
        DailySnapshot(
            date=date(2025, 6, 1), scope_type="loan", scope_id="1",
            value_eur=Decimal("-10000.10"),
        )
    )
    db_session.add(
        DailySnapshot(
            date=date(2025, 6, 1), scope_type="loan", scope_id="2",
            value_eur=Decimal("-5000.20"),
        )
    )
    db_session.commit()

    total = _total_on(db_session, "loan", None, date(2025, 6, 1))
    assert total == Decimal("-15000.30")
    assert str(total) == "-15000.30"
