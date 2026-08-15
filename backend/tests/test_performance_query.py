"""Integration tests for the DB-facing half of return metrics
(performance_query.py) — booked through the real transaction API per ADR
0013, then checked against hand-derived expectations for exactly what
value_series/flow_events should extract from that data. The return-math
itself (chaining, XIRR) is already exhaustively unit-tested in
test_performance_service.py; this file only checks the DB extraction is
correct, plus one end-to-end sanity pass through the router.

Invented ISINs and quantities only, per AGENTS.md.
"""

from datetime import date
from decimal import Decimal

import pytest


def _setup_scenario(client, auth_headers, db_session):
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
            "isin": "XX0000000600",
            "asset_class": "EQUITY",
            "valuation_mode": "MARKET",
            "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]

    # BUY 10 @ 100 on day 1; price jumps to 110 on day 10 (no txn, pure
    # market move); BUY 5 more @ 110 on day 15; SELL 5 @ 120 on day 20,
    # with the price also moving to 120 that same day.
    for d, close in [(date(2024, 1, 1), "100.00"), (date(2024, 1, 10), "110.00"),
                      (date(2024, 1, 20), "120.00")]:
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
            "external_id": "perf-buy-1", "date": "2024-01-01", "type": "BUY",
            "account_id": account, "instrument_id": instrument,
            "quantity": "10", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    client.post(
        "/api/transactions",
        json={
            "external_id": "perf-buy-2", "date": "2024-01-15", "type": "BUY",
            "account_id": account, "instrument_id": instrument,
            "quantity": "5", "price": "110.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    client.post(
        "/api/transactions",
        json={
            "external_id": "perf-sell-1", "date": "2024-01-20", "type": "SELL",
            "account_id": account, "instrument_id": instrument,
            "quantity": "5", "price": "120.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    client.post("/api/admin/rebuild-snapshots", headers=auth_headers)
    return account, instrument


def test_value_series_matches_expected_daily_values(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.performance_query import ScopeFilter, value_series

    _setup_scenario(client, auth_headers, db_session)

    db = SessionLocal()
    try:
        series = value_series(db, ScopeFilter(), date(2024, 1, 1), date(2024, 1, 21))
    finally:
        db.close()

    by_date = dict(series)
    assert by_date[date(2024, 1, 1)] == Decimal("1000.00")
    assert by_date[date(2024, 1, 9)] == Decimal("1000.00")
    assert by_date[date(2024, 1, 10)] == Decimal("1100.00")
    assert by_date[date(2024, 1, 14)] == Decimal("1100.00")
    assert by_date[date(2024, 1, 15)] == Decimal("1650.00")
    assert by_date[date(2024, 1, 19)] == Decimal("1650.00")
    assert by_date[date(2024, 1, 20)] == Decimal("1200.00")
    assert by_date[date(2024, 1, 21)] == Decimal("1200.00")


def test_flow_events_are_buy_positive_sell_negative(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.performance_query import ScopeFilter, flow_events

    _setup_scenario(client, auth_headers, db_session)

    db = SessionLocal()
    try:
        flows = flow_events(db, ScopeFilter(), date(2024, 1, 1), date(2024, 1, 21))
    finally:
        db.close()

    by_date = {f.date: f.amount for f in flows}
    assert by_date[date(2024, 1, 1)] == Decimal("1000.00")
    assert by_date[date(2024, 1, 15)] == Decimal("550.00")
    assert by_date[date(2024, 1, 20)] == Decimal("-600.00")


def test_value_series_empty_before_any_position(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.performance_query import ScopeFilter, value_series

    _setup_scenario(client, auth_headers, db_session)

    db = SessionLocal()
    try:
        series = value_series(db, ScopeFilter(), date(2023, 12, 25), date(2023, 12, 31))
    finally:
        db.close()

    assert all(v == Decimal(0) for _, v in series)


def test_performance_endpoint_twr_end_to_end(client, auth_headers, db_session):
    _setup_scenario(client, auth_headers, db_session)

    resp = client.get(
        "/api/performance",
        params={"scope": "total", "period": "inception", "method": "twr"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["method"] == "twr"
    assert body["curve"] is not None
    assert len(body["curve"]) > 0
    assert isinstance(body["return_pct"], float)
    # Hand-derived from the scenario: the only two days with a genuine
    # market move (excluding flow-explained jumps) are day10 (+10%) and
    # the day20 sell (net +150/1650, see test_performance_service.py's
    # docstring reasoning for why the sold lot's gain is invisible here).
    # Chained: (1.10 * (1 + 150/1650)) - 1.
    expected = (Decimal("1.10") * (Decimal(1) + Decimal(150) / Decimal(1650))) - Decimal(1)
    assert body["return_pct"] == pytest.approx(float(expected), abs=1e-6)


def test_performance_endpoint_mwr_end_to_end(client, auth_headers, db_session):
    _setup_scenario(client, auth_headers, db_session)

    resp = client.get(
        "/api/performance",
        params={"scope": "total", "period": "inception", "method": "mwr"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["method"] == "mwr"
    assert body["curve"] is None
    assert isinstance(body["return_pct"], float)


def test_performance_endpoint_benchmark_overlay(client, auth_headers, db_session):
    from app.models import PricePoint

    _setup_scenario(client, auth_headers, db_session)

    benchmark = client.post(
        "/api/instruments",
        json={
            "name": "World ETF", "isin": "XX0000000601",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    for d, close in [(date(2024, 1, 1), "50.00"), (date(2024, 1, 20), "55.00")]:
        db_session.add(
            PricePoint(
                instrument_id=benchmark, date=d, close=Decimal(close),
                currency="EUR", provider="test", quality="ok",
            )
        )
    db_session.commit()

    resp = client.get(
        "/api/performance",
        params={
            "scope": "total", "period": "inception", "method": "twr",
            "benchmark_instrument_id": benchmark,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["benchmark_curve"] is not None
    assert len(body["benchmark_curve"]) == len(body["curve"])
    # Benchmark moved 50 -> 55 = +10% over the window, with the *same*
    # flow schedule as the real portfolio (which never sold anything
    # into the benchmark) -> its own TWR should read exactly 10%.
    last = body["benchmark_curve"][-1]["index_value"]
    assert last == pytest.approx(110.0, abs=1e-6)


def test_performance_endpoint_no_benchmark_curve_when_not_requested(client, auth_headers, db_session):
    _setup_scenario(client, auth_headers, db_session)
    resp = client.get(
        "/api/performance",
        params={"scope": "total", "period": "inception", "method": "twr"},
        headers=auth_headers,
    )
    assert resp.json()["benchmark_curve"] is None


def test_performance_endpoint_rejects_invalid_scope(client, auth_headers):
    resp = client.get(
        "/api/performance", params={"scope": "bogus"}, headers=auth_headers
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_scope"


def test_performance_endpoint_requires_auth(client):
    resp = client.get("/api/performance")
    assert resp.status_code == 401
