"""Reproductions for two window-boundary bugs that live at the
performance_query.py / performance_service.py / routers/performance.py
seam — grouped in one file because they share a root cause (a flow dated
exactly on the return window's boundary being mishandled) and neither
has a better-fitting owned test file.

Bug 1 (the severe one): MWR counted the opening position twice. Because
`flow_events` is inclusive of `start`, and the pre-fix router took
`start_value` from the snapshot *on* `start` (which already reflects
that day's trade), `mwr()` was handed both `(start, -start_value)` and
`(that same day, -that same trade's amount)` as two separate outflows.
Since `period="inception"` always resolves `start` to the very first
transaction's own date, every inception MWR was guaranteed wrong. Fixed
in routers/performance.py by sourcing `start_value` from the day
*before* `start` instead (zero at true inception) — see the comment
there and in performance_service.py's `mwr()` docstring.

Bug 6: `OPENING_BALANCE` (spec 2.5's backfill workflow) creates a
position/snapshot value with no matching flow, so a backfill was
misread entirely as market return. Fixed in performance_query.py's
`flow_events` by treating OPENING_BALANCE as a flow, the same as BUY.

Invented ISINs and amounts only, per AGENTS.md.
"""

from datetime import date, timedelta
from decimal import Decimal


def test_mwr_is_not_negative_for_a_monotonically_rising_position(
    client, auth_headers, db_session
):
    """A position that only ever gains value (no sells, no price drops)
    can never have a genuinely negative money-weighted return. Pre-fix,
    the day-one double count of the opening BUY made this read strongly
    negative (~-47% on the bug's own reproduction data); the true
    figure is positive. `period=inception` is exactly the case that's
    *guaranteed* wrong pre-fix, since inception always resolves `start`
    to the first transaction's own date."""
    from app.models import PricePoint

    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio MWR", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "MWR Test ETF",
            "isin": "XX0000000900",
            "asset_class": "EQUITY",
            "valuation_mode": "MARKET",
            "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]

    # Day 1 (== inception's window start): BUY 10 @ 100 = 1000.00. This
    # is the exact flow that used to get double-counted as both
    # start_value and a same-day flow.
    for d, close in [
        (date(2024, 1, 1), "100.00"),
        (date(2024, 3, 10), "110.00"),
        (date(2024, 8, 1), "140.00"),
    ]:
        db_session.add(
            PricePoint(
                instrument_id=instrument, date=d, close=Decimal(close),
                currency="EUR", provider="test", quality="ok",
            )
        )
    db_session.commit()

    client.post(
        "/api/transactions",
        json={
            "external_id": "mwr-buy-1", "date": "2024-01-01", "type": "BUY",
            "account_id": account, "instrument_id": instrument,
            "quantity": "10", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    # A second contribution later, at the new (higher) price -- more
    # money in, never a loss anywhere in the series.
    client.post(
        "/api/transactions",
        json={
            "external_id": "mwr-buy-2", "date": "2024-03-10", "type": "BUY",
            "account_id": account, "instrument_id": instrument,
            "quantity": "5", "price": "110.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    client.post("/api/admin/rebuild-snapshots", headers=auth_headers)

    resp = client.get(
        "/api/performance",
        params={"scope": "total", "period": "inception", "method": "mwr"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["return_pct"] is not None
    # Unambiguous sign check (per the brief): a monotonically rising
    # position must not produce a negative MWR. Also bound it away from
    # the absurd magnitudes a double-counted opening position produces.
    assert body["return_pct"] > 0
    assert body["return_pct"] < 5.0

    # TWR must still be unaffected by this fix (it never used the
    # same-day flow in the first place -- daily_returns only reads
    # flow(d1), never flow(d0) -- so it's a separate code path).
    twr_resp = client.get(
        "/api/performance",
        params={"scope": "total", "period": "inception", "method": "twr"},
        headers=auth_headers,
    )
    assert twr_resp.status_code == 200
    assert twr_resp.json()["return_pct"] > 0


def test_opening_balance_counts_as_a_flow_not_market_return(
    client, auth_headers, db_session
):
    """Booking an OPENING_BALANCE worth 500.00 into a portfolio already
    holding 1000.00, with zero price movement anywhere, must read as a
    0% return for that day -- not +50%, which is what happens if the
    backfill is invisible to flow_events and gets treated as pure
    organic growth."""
    from app.database import SessionLocal
    from app.models import PricePoint
    from app.performance_query import ScopeFilter, flow_events, value_series
    from app.performance_service import daily_returns

    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio Backfill", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    held = client.post(
        "/api/instruments",
        json={
            "name": "Already Held ETF",
            "isin": "XX0000000901",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    backfilled = client.post(
        "/api/instruments",
        json={
            "name": "Backfilled ETF",
            "isin": "XX0000000902",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]

    day0 = date(2024, 1, 1)
    opening_day = date(2024, 1, 10)

    db_session.add(
        PricePoint(
            instrument_id=held, date=day0, close=Decimal("100.00"),
            currency="EUR", provider="test", quality="ok",
        )
    )
    db_session.add(
        PricePoint(
            instrument_id=backfilled, date=opening_day, close=Decimal("100.00"),
            currency="EUR", provider="test", quality="ok",
        )
    )
    db_session.commit()

    # Pre-existing 1000.00 position, well before the window under test.
    client.post(
        "/api/transactions",
        json={
            "external_id": "backfill-buy-1", "date": str(day0), "type": "BUY",
            "account_id": account, "instrument_id": held,
            "quantity": "10", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    # The backfill: 5 units @ 100.00 = 500.00, registered without any
    # trade actually happening that day.
    client.post(
        "/api/transactions",
        json={
            "external_id": "backfill-opening-1", "date": str(opening_day),
            "type": "OPENING_BALANCE",
            "account_id": account, "instrument_id": backfilled,
            "quantity": "5", "amount": "500.00", "currency": "EUR",
            "provisional": False,
        },
        headers=auth_headers,
    )
    client.post("/api/admin/rebuild-snapshots", headers=auth_headers)

    db = SessionLocal()
    try:
        window_start = opening_day - timedelta(days=1)
        values = value_series(db, ScopeFilter(), window_start, opening_day)
        flows = flow_events(db, ScopeFilter(), window_start, opening_day)
    finally:
        db.close()

    by_date_value = dict(values)
    assert by_date_value[window_start] == Decimal("1000.00")
    assert by_date_value[opening_day] == Decimal("1500.00")

    # The fix: the OPENING_BALANCE now shows up as a flow.
    by_date_flow = {f.date: f.amount for f in flows}
    assert by_date_flow[opening_day] == Decimal("500.00")

    returns = daily_returns(values, flows)
    assert len(returns) == 1
    assert returns[0] == (opening_day, Decimal("0"))
