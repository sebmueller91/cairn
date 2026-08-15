"""Golden-scenario test for the attribution waterfall (spec 4.3). Exercises
every named bucket at once and checks both the exact-sum invariant
(guaranteed by construction, but worth verifying the implementation
actually satisfies it) and specific hand-derived bucket values — including
working through the "phantom income/cost" consequence documented in
attribution_service.py's module docstring, since it's the least obvious
part of the design.

Invented ISINs, quantities, and amounts only, per AGENTS.md.
"""

from datetime import date, timedelta
from decimal import Decimal


def _setup(client, auth_headers, db_session):
    from app.models import PricePoint, ValuationAnchor

    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    cash_account = client.post(
        "/api/accounts",
        json={"name": "Girokonto", "type": "CASH", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    etf = client.post(
        "/api/instruments",
        json={
            "name": "Test ETF", "isin": "XX0000000700",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    house_account = client.post(
        "/api/accounts",
        json={"name": "Home", "type": "REAL_ESTATE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    house = client.post(
        "/api/instruments",
        json={
            "name": "Test House", "isin": None,
            "asset_class": "REAL_ESTATE", "valuation_mode": "ANCHORED", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]

    # Day 1: buy the ETF, open the cash account, buy the house (anchor +
    # the OPENING_BALANCE that actually registers it as a position — an
    # anchor alone never touches ledger.py's quantity-bearing events, so
    # without this the house would be entirely invisible to the snapshot
    # engine, contributing nothing to gross wealth at all).
    client.post(
        "/api/transactions",
        json={
            "external_id": "attr-buy-1", "date": "2024-01-01", "type": "BUY",
            "account_id": account, "instrument_id": etf,
            "quantity": "10", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    client.post(
        "/api/transactions",
        json={
            "external_id": "attr-stmt-1", "date": "2024-01-01", "type": "BALANCE_STATEMENT",
            "account_id": cash_account, "amount": "500.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    client.post(
        "/api/transactions",
        json={
            "external_id": "attr-house-opening-1", "date": "2024-01-01", "type": "OPENING_BALANCE",
            "account_id": house_account, "instrument_id": house,
            "quantity": "1", "amount": "300000.00", "currency": "EUR", "provisional": False,
        },
        headers=auth_headers,
    )
    db_session.add(
        ValuationAnchor(
            instrument_id=house, date=date(2024, 1, 1), value_eur=Decimal("300000.00"),
            method="purchase",
        )
    )
    # A price_point for the ETF's own purchase day is needed too — an
    # explicit BUY price never auto-populates price_point, that table is
    # a separate fetched/backfilled series (test_timeseries_and_admin.py
    # follows the same pattern).
    db_session.add(
        PricePoint(
            instrument_id=etf, date=date(2024, 1, 1), close=Decimal("100.00"),
            currency="EUR", provider="test", quality="ok",
        )
    )
    # Day 10: pure market move, no transaction.
    db_session.add(
        PricePoint(
            instrument_id=etf, date=date(2024, 1, 10), close=Decimal("110.00"),
            currency="EUR", provider="test", quality="ok",
        )
    )
    db_session.commit()

    # Day 15: dividend income + a standalone fee (not tied to a trade).
    client.post(
        "/api/transactions",
        json={
            "external_id": "attr-div-1", "date": "2024-01-15", "type": "DIVIDEND",
            "account_id": account, "instrument_id": etf,
            "amount": "50.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    client.post(
        "/api/transactions",
        json={
            "external_id": "attr-fee-1", "date": "2024-01-15", "type": "FEE",
            "account_id": account, "amount": "5.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    # Day 20: house re-appraised higher.
    db_session.add(
        ValuationAnchor(
            instrument_id=house, date=date(2024, 1, 20), value_eur=Decimal("320000.00"),
            method="appraisal",
        )
    )
    db_session.commit()
    # Day 30 (= the window's end): cash balance moved up (savings/
    # residual). Dated exactly at `end` rather than mid-period, since
    # cash interpolation never extrapolates past its last known
    # statement (a real, pre-existing characteristic of this app — see
    # cash_service.py) — a statement mid-window would leave the cash
    # account's value undefined right at the measurement point.
    client.post(
        "/api/transactions",
        json={
            "external_id": "attr-stmt-2", "date": "2024-01-30", "type": "BALANCE_STATEMENT",
            "account_id": cash_account, "amount": "700.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    client.post("/api/admin/rebuild-snapshots", headers=auth_headers)


def test_attribution_buckets_sum_to_observed_delta(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.attribution_service import compute_attribution

    _setup(client, auth_headers, db_session)

    db = SessionLocal()
    try:
        result = compute_attribution(db, date(2024, 1, 1), date(2024, 1, 30))
    finally:
        db.close()

    named_sum = (
        result.deposits_withdrawals
        + result.income
        + result.costs
        + result.valuation_adjustments
        + result.fx_effect
        + result.market_gains_losses
    )
    assert named_sum == result.end_value - result.start_value


def test_attribution_bucket_values_match_hand_derivation(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.attribution_service import compute_attribution

    _setup(client, auth_headers, db_session)

    db = SessionLocal()
    try:
        result = compute_attribution(db, date(2024, 1, 1), date(2024, 1, 30))
    finally:
        db.close()

    # gross(day1) = 1000 (ETF) + 500 (cash) + 300000 (house) = 301500
    # gross(day30) = 1100 (ETF @110) + 700 (cash) + 320000 (house) = 321800
    assert result.start_value == Decimal("301500.00")
    assert result.end_value == Decimal("321800.00")

    # The day-1 BUY is already baked into start_value (date > start
    # excludes it); only the cash balance's own change remains.
    assert result.deposits_withdrawals == Decimal("200.00")
    assert result.income == Decimal("50.00")
    assert result.costs == Decimal("-5.00")
    assert result.valuation_adjustments == Decimal("20000.00")
    assert result.fx_effect == Decimal("0")

    # Residual = true organic ETF gain (1000 -> 1100 = +100) minus the
    # dividend and fee's *claimed* bucket amounts, which never actually
    # moved gross wealth (neither reinvested nor paid from a tracked cash
    # account) — the documented "phantom income/cost" consequence:
    # 100 - 50 (unreflected income) + 5 (unreflected cost) = 55.
    assert result.market_gains_losses == Decimal("55.00")


def test_month_end_boundaries_partitions_the_range():
    from app.attribution_service import month_end_boundaries

    boundaries = month_end_boundaries(date(2024, 1, 15), date(2024, 3, 10))
    assert boundaries == [
        date(2024, 1, 15),
        date(2024, 1, 31),
        date(2024, 2, 29),  # 2024 is a leap year
        date(2024, 3, 10),
    ]


def test_attribution_series_monthly(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.attribution_service import attribution_series

    _setup(client, auth_headers, db_session)

    db = SessionLocal()
    try:
        series = attribution_series(db, date(2024, 1, 1), date(2024, 2, 15), "month")
    finally:
        db.close()

    assert [b.end_date for b in series] == [date(2024, 1, 31), date(2024, 2, 15)]
    # Every period still individually satisfies the sum invariant.
    for bucket in series:
        named_sum = (
            bucket.deposits_withdrawals
            + bucket.income
            + bucket.costs
            + bucket.valuation_adjustments
            + bucket.fx_effect
            + bucket.market_gains_losses
        )
        assert named_sum == bucket.end_value - bucket.start_value


def test_attribution_endpoint_end_to_end(client, auth_headers, db_session):
    _setup(client, auth_headers, db_session)

    resp = client.get(
        "/api/attribution",
        params={"from": "2024-01-01", "to": "2024-01-30", "granularity": "month"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["granularity"] == "month"
    assert len(body["periods"]) == 1
    period = body["periods"][0]
    assert period["income"] == "50.00"
    assert period["costs"] == "-5.00"
    assert period["valuation_adjustments"] == "20000.00"
    assert period["market_gains_losses"] == "55.00"


def test_attribution_endpoint_requires_auth(client):
    resp = client.get("/api/attribution")
    assert resp.status_code == 401


def test_attribution_endpoint_rejects_bad_range(client, auth_headers):
    resp = client.get(
        "/api/attribution",
        params={"from": "2024-06-01", "to": "2024-01-01"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_range"


def test_attribution_endpoint_clamps_explicit_to_beyond_available_data(
    client, auth_headers, db_session
):
    """When `to` is explicitly requested past the newest snapshot row,
    the honest response clamps to what actually exists rather than
    reading a missing end-of-window snapshot as a Decimal(0) portfolio
    (which would previously dump the entire real end_value into the
    market_gains_losses residual as a giant phantom loss)."""
    _setup(client, auth_headers, db_session)

    resp = client.get(
        "/api/attribution",
        params={"from": "2024-01-01", "to": "2099-12-31", "granularity": "year"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["periods"], "expected at least one period"
    last_period = body["periods"][-1]
    assert last_period["end_date"] != "2099-12-31"
    assert Decimal(last_period["end_value"]) > 0
    # Hand-derived sanity from _setup: real gross wealth stays in the
    # hundreds-of-thousands range throughout, nowhere near a five/six
    # figure negative residual.
    assert Decimal(last_period["market_gains_losses"]) > Decimal("-1000.00")


def test_attribution_endpoint_clamps_default_end_when_today_has_no_snapshot_yet(
    client, auth_headers, db_session, monkeypatch
):
    """Same staleness bug as performance's (see test_performance_query.py),
    reproduced for attribution's default `to = date.today()` path: the
    daily_snapshot table only extends through the last rebuild (here,
    real "today"), but a caller hitting the endpoint moments after
    midnight and before the nightly job sees date.today() one day ahead
    of that."""
    import app.routers.attribution as attr_router
    from app.models import DailySnapshot

    _setup(client, auth_headers, db_session)

    real_latest = (
        db_session.query(DailySnapshot.date)
        .filter(DailySnapshot.scope_type == "total", DailySnapshot.scope_id == "gross")
        .order_by(DailySnapshot.date.desc())
        .first()[0]
    )
    fake_today = real_latest + timedelta(days=1)

    class FakeDate(date):
        @classmethod
        def today(cls):
            return fake_today

    monkeypatch.setattr(attr_router, "date", FakeDate)

    resp = client.get(
        "/api/attribution",
        params={"from": "2024-01-01", "granularity": "month"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["periods"], "expected at least one period"
    last_period = body["periods"][-1]
    assert last_period["end_date"] == real_latest.isoformat()
    assert Decimal(last_period["market_gains_losses"]) > Decimal("-1000.00")


def test_attribution_endpoint_sane_when_no_snapshots_exist_at_all(client, auth_headers):
    """No transactions booked, no rebuild ever run: the endpoint must
    still respond (never crash). With an explicit range it still
    partitions into periods (per month_end_boundaries), but every bucket
    reads as flat zero rather than fabricating a phantom loss."""
    resp = client.get(
        "/api/attribution",
        params={"from": "2024-01-01", "to": "2024-06-01", "granularity": "month"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["periods"]
    for period in body["periods"]:
        assert Decimal(period["start_value"]) == 0
        assert Decimal(period["end_value"]) == 0
        assert Decimal(period["market_gains_losses"]) == 0

    # With no `from` given either, start falls back to `end` itself, so
    # there's nothing to partition into periods at all.
    resp_no_from = client.get(
        "/api/attribution",
        params={"granularity": "month"},
        headers=auth_headers,
    )
    assert resp_no_from.status_code == 200
    assert resp_no_from.json()["periods"] == []
