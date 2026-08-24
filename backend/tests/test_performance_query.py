"""Integration tests for the DB-facing half of return metrics
(performance_query.py) — booked through the real transaction API per ADR
0013, then checked against hand-derived expectations for exactly what
value_series/flow_events should extract from that data. The return-math
itself (chaining, XIRR) is already exhaustively unit-tested in
test_performance_service.py; this file only checks the DB extraction is
correct, plus one end-to-end sanity pass through the router.

Invented ISINs and quantities only, per AGENTS.md.
"""

from datetime import date, timedelta
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


def test_performance_endpoint_clamps_end_when_today_has_no_snapshot_yet(
    client, auth_headers, db_session, monkeypatch
):
    """Reproduces the "midnight to nightly-rebuild" staleness bug: the
    daily_snapshot table only extends through the last night's rebuild
    (here: real "today", since the test's own rebuild-snapshots call just
    ran), but the endpoint defaults its window's end to whatever
    date.today() returns *right now*. Simulate the gap by making the
    router believe "today" is one calendar day past the newest snapshot
    row that actually exists — exactly the state the app is in for a few
    hours every morning before the 23:00 job catches up. Pre-fix, this
    should show a phantom ~-100% TWR (the extra day's V(t) zero-fills)
    and an MWR end_value of zero; post-fix, both should clamp to the
    real latest snapshot date instead."""
    import app.routers.performance as perf_router
    from app.models import DailySnapshot

    _setup_scenario(client, auth_headers, db_session)

    real_latest = (
        db_session.query(DailySnapshot.date)
        .filter(DailySnapshot.scope_type == "total")
        .order_by(DailySnapshot.date.desc())
        .first()[0]
    )
    fake_today = real_latest + timedelta(days=1)

    class FakeDate(date):
        @classmethod
        def today(cls):
            return fake_today

    monkeypatch.setattr(perf_router, "date", FakeDate)

    resp_twr = client.get(
        "/api/performance",
        params={"scope": "total", "period": "inception", "method": "twr"},
        headers=auth_headers,
    )
    assert resp_twr.status_code == 200
    body_twr = resp_twr.json()
    # The clamp must be visible in the response, not just internally applied.
    assert body_twr["end_date"] == real_latest.isoformat()
    assert body_twr["return_pct"] is not None
    # Sanity-derived from _setup_scenario: real return is a small positive
    # figure (see test_performance_endpoint_twr_end_to_end). The bug
    # produces something close to -1.0 (-100%); anything above -0.5 rules
    # that phantom out.
    assert body_twr["return_pct"] > -0.5
    assert all(
        point["date"] != fake_today.isoformat() for point in body_twr["curve"]
    )

    resp_mwr = client.get(
        "/api/performance",
        params={"scope": "total", "period": "inception", "method": "mwr"},
        headers=auth_headers,
    )
    assert resp_mwr.status_code == 200
    body_mwr = resp_mwr.json()
    assert body_mwr["end_date"] == real_latest.isoformat()
    assert body_mwr["return_pct"] is not None
    assert body_mwr["return_pct"] > -0.9


def test_performance_endpoint_sane_when_no_snapshots_exist_at_all(client, auth_headers):
    """No transactions booked, no rebuild ever run: the endpoint must
    still respond (never crash), with an empty/None result rather than
    fabricating anything."""
    resp = client.get(
        "/api/performance",
        params={"scope": "total", "period": "1Y", "method": "twr"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["return_pct"] is None
    assert body["curve"] == []

    resp_mwr = client.get(
        "/api/performance",
        params={"scope": "total", "period": "1Y", "method": "mwr"},
        headers=auth_headers,
    )
    assert resp_mwr.status_code == 200
    assert resp_mwr.json()["return_pct"] is None


# --------------------------------------------------------------------
# Asset-class filter
# --------------------------------------------------------------------


def _setup_two_class_scenario(client, auth_headers, db_session):
    """One equity and one crypto position, deliberately moving in
    opposite directions so a filtered series cannot accidentally match
    the unfiltered one.

    Equity: buy 10 @ 100 on Jan 1, price 120 from Jan 10 (+20%).
    Crypto: buy 2 @ 500 on Jan 1, price 400 from Jan 10 (-20%).
    """
    from app.models import PricePoint

    account = client.post(
        "/api/accounts",
        json={"name": "Mixed", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]

    ids = {}
    for name, isin, cls in [
        ("Equity ETF", "XX0000000710", "EQUITY"),
        ("Coin", "XX0000000720", "CRYPTO"),
    ]:
        ids[cls] = client.post(
            "/api/instruments",
            json={
                "name": name, "isin": isin, "asset_class": cls,
                "valuation_mode": "MARKET", "currency": "EUR",
            },
            headers=auth_headers,
        ).json()["id"]

    for cls, day1, day10 in [("EQUITY", "100.00", "120.00"), ("CRYPTO", "500.00", "400.00")]:
        for d, close in [(date(2024, 1, 1), day1), (date(2024, 1, 10), day10)]:
            db_session.add(
                PricePoint(
                    instrument_id=ids[cls], date=d, close=Decimal(close),
                    currency="EUR", provider="test", quality="ok",
                )
            )
    db_session.commit()

    for cls, qty, price in [("EQUITY", "10", "100.00"), ("CRYPTO", "2", "500.00")]:
        client.post(
            "/api/transactions",
            json={
                "external_id": f"acf-buy-{cls}", "date": "2024-01-01", "type": "BUY",
                "account_id": account, "instrument_id": ids[cls],
                "quantity": qty, "price": price, "currency": "EUR",
            },
            headers=auth_headers,
        )
    client.post("/api/admin/rebuild-snapshots", headers=auth_headers)
    return account, ids


def test_parse_asset_classes_accepts_a_list_and_rejects_junk():
    from app.models import AssetClass
    from app.performance_query import InvalidAssetClassError, parse_asset_classes

    assert parse_asset_classes(None) is None
    assert parse_asset_classes("") is None
    assert parse_asset_classes("  ") is None
    assert parse_asset_classes("EQUITY,CRYPTO") == frozenset(
        {AssetClass.EQUITY, AssetClass.CRYPTO}
    )
    # Whitespace and a trailing comma are the shapes a URL builder emits.
    assert parse_asset_classes("EQUITY , BOND,") == frozenset(
        {AssetClass.EQUITY, AssetClass.BOND}
    )
    with pytest.raises(InvalidAssetClassError):
        parse_asset_classes("EQUITY,NOT_A_CLASS")


def test_value_series_restricted_to_selected_asset_classes(
    client, auth_headers, db_session
):
    from app.database import SessionLocal
    from app.models import AssetClass
    from app.performance_query import ScopeFilter, value_series

    _setup_two_class_scenario(client, auth_headers, db_session)

    db = SessionLocal()
    try:
        both = dict(value_series(db, ScopeFilter(), date(2024, 1, 1), date(2024, 1, 11)))
        equity = dict(
            value_series(
                db,
                ScopeFilter(asset_classes=frozenset({AssetClass.EQUITY})),
                date(2024, 1, 1),
                date(2024, 1, 11),
            )
        )
        crypto = dict(
            value_series(
                db,
                ScopeFilter(asset_classes=frozenset({AssetClass.CRYPTO})),
                date(2024, 1, 1),
                date(2024, 1, 11),
            )
        )
    finally:
        db.close()

    # Jan 1: equity 1000, crypto 1000, together 2000.
    assert equity[date(2024, 1, 1)] == Decimal("1000.00")
    assert crypto[date(2024, 1, 1)] == Decimal("1000.00")
    assert both[date(2024, 1, 1)] == Decimal("2000.00")
    # Jan 10: equity 1200 (+20%), crypto 800 (-20%) — the two moves
    # cancel in the total, which is exactly why the filtered series has
    # to be computed rather than derived from it.
    assert equity[date(2024, 1, 10)] == Decimal("1200.00")
    assert crypto[date(2024, 1, 10)] == Decimal("800.00")
    assert both[date(2024, 1, 10)] == Decimal("2000.00")


def test_flow_events_restricted_to_selected_asset_classes(
    client, auth_headers, db_session
):
    """The filter must reach the flows too. A value series narrowed to
    equities while the flows still carried the crypto purchase would
    book that contribution as pure return."""
    from app.database import SessionLocal
    from app.models import AssetClass
    from app.performance_query import ScopeFilter, flow_events

    _setup_two_class_scenario(client, auth_headers, db_session)

    db = SessionLocal()
    try:
        both = flow_events(db, ScopeFilter(), date(2024, 1, 1), date(2024, 1, 11))
        equity = flow_events(
            db,
            ScopeFilter(asset_classes=frozenset({AssetClass.EQUITY})),
            date(2024, 1, 1),
            date(2024, 1, 11),
        )
    finally:
        db.close()

    assert sum(f.amount for f in both) == Decimal("2000.00")
    assert sum(f.amount for f in equity) == Decimal("1000.00")


def test_inception_respects_the_asset_class_filter(client, auth_headers, db_session):
    """`period=inception` must start where the *filtered* holding began,
    not where the portfolio did."""
    from app.database import SessionLocal
    from app.models import AssetClass, PricePoint
    from app.performance_query import ScopeFilter, inception_date

    account, ids = _setup_two_class_scenario(client, auth_headers, db_session)
    # A bond bought much later than the Jan 1 equity/crypto pair.
    bond = client.post(
        "/api/instruments",
        json={
            "name": "Bond Fund", "isin": "XX0000000730", "asset_class": "BOND",
            "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    db_session.add(
        PricePoint(
            instrument_id=bond, date=date(2024, 3, 1), close=Decimal("50.00"),
            currency="EUR", provider="test", quality="ok",
        )
    )
    db_session.commit()
    client.post(
        "/api/transactions",
        json={
            "external_id": "acf-buy-bond", "date": "2024-03-01", "type": "BUY",
            "account_id": account, "instrument_id": bond,
            "quantity": "10", "price": "50.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    client.post("/api/admin/rebuild-snapshots", headers=auth_headers)

    db = SessionLocal()
    try:
        overall = inception_date(db, ScopeFilter())
        bonds_only = inception_date(
            db, ScopeFilter(asset_classes=frozenset({AssetClass.BOND}))
        )
    finally:
        db.close()

    assert overall == date(2024, 1, 1)
    assert bonds_only == date(2024, 3, 1)


def test_performance_endpoint_filtered_return_differs_from_total(
    client, auth_headers, db_session
):
    _setup_two_class_scenario(client, auth_headers, db_session)

    total = client.get(
        "/api/performance",
        params={"scope": "total", "period": "inception", "method": "twr"},
        headers=auth_headers,
    ).json()
    equity = client.get(
        "/api/performance",
        params={
            "scope": "total", "period": "inception", "method": "twr",
            "asset_classes": "EQUITY",
        },
        headers=auth_headers,
    ).json()
    crypto = client.get(
        "/api/performance",
        params={
            "scope": "total", "period": "inception", "method": "twr",
            "asset_classes": "CRYPTO",
        },
        headers=auth_headers,
    ).json()

    # +20% and -20% cancel out across the whole portfolio; each leg on
    # its own is the real number the filter exists to surface.
    assert total["return_pct"] == pytest.approx(0.0, abs=1e-9)
    assert equity["return_pct"] == pytest.approx(0.20, abs=1e-9)
    assert crypto["return_pct"] == pytest.approx(-0.20, abs=1e-9)


def test_performance_endpoint_listing_every_class_matches_unfiltered(
    client, auth_headers, db_session
):
    """A filter naming everything must be identical to no filter — this
    is what the UI sends the moment a user toggles a class back on."""
    _setup_two_class_scenario(client, auth_headers, db_session)

    unfiltered = client.get(
        "/api/performance",
        params={"scope": "total", "period": "inception", "method": "twr"},
        headers=auth_headers,
    ).json()
    everything = client.get(
        "/api/performance",
        params={
            "scope": "total", "period": "inception", "method": "twr",
            "asset_classes": "EQUITY,BOND,COMMODITY,CRYPTO,REAL_ESTATE,VEHICLE,CASH,LIABILITY",
        },
        headers=auth_headers,
    ).json()

    assert everything["return_pct"] == unfiltered["return_pct"]
    assert everything["curve"] == unfiltered["curve"]


def test_performance_endpoint_benchmark_follows_the_filter(
    client, auth_headers, db_session
):
    """The shadow portfolio mirrors the real one's flows, so filtering
    must change what the benchmark is compared against — otherwise the
    overlay silently compares MSCI World to a portfolio that includes
    holdings the user just excluded."""
    from app.models import PricePoint

    account, ids = _setup_two_class_scenario(client, auth_headers, db_session)
    benchmark = client.post(
        "/api/instruments",
        json={
            "name": "Index", "isin": "XX0000000740", "asset_class": "EQUITY",
            "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    for d, close in [(date(2024, 1, 1), "10.00"), (date(2024, 1, 10), "11.00")]:
        db_session.add(
            PricePoint(
                instrument_id=benchmark, date=d, close=Decimal(close),
                currency="EUR", provider="test", quality="ok",
            )
        )
    db_session.commit()

    unfiltered = client.get(
        "/api/performance",
        params={
            "scope": "total", "period": "inception", "method": "twr",
            "benchmark_instrument_id": benchmark,
        },
        headers=auth_headers,
    ).json()
    filtered = client.get(
        "/api/performance",
        params={
            "scope": "total", "period": "inception", "method": "twr",
            "benchmark_instrument_id": benchmark, "asset_classes": "EQUITY",
        },
        headers=auth_headers,
    ).json()

    # Both benchmark curves end at +10% (the index moved 10 -> 11) — the
    # shadow tracks the index, not the portfolio. What must differ is the
    # portfolio curve it is drawn against.
    assert unfiltered["benchmark_curve"][-1]["index_value"] == pytest.approx(110.0, abs=1e-6)
    assert filtered["benchmark_curve"][-1]["index_value"] == pytest.approx(110.0, abs=1e-6)
    assert unfiltered["curve"][-1]["index_value"] == pytest.approx(100.0, abs=1e-6)
    assert filtered["curve"][-1]["index_value"] == pytest.approx(120.0, abs=1e-6)


def test_performance_endpoint_rejects_an_unknown_asset_class(client, auth_headers):
    resp = client.get(
        "/api/performance",
        params={"scope": "total", "asset_classes": "EQUITY,GOLD_BARS"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_asset_class"


def test_performance_endpoint_empty_when_filter_matches_nothing(
    client, auth_headers, db_session
):
    """Selecting a class with no MARKET holdings must degrade to "no
    data", not crash and not silently fall back to the whole portfolio."""
    _setup_two_class_scenario(client, auth_headers, db_session)

    resp = client.get(
        "/api/performance",
        params={"scope": "total", "period": "inception", "asset_classes": "VEHICLE"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["return_pct"] is None
    assert not body["curve"]


def test_benchmark_overlay_works_when_no_flows_fall_inside_the_window(
    client, auth_headers, db_session
):
    """The shadow portfolio used to be funded only by contributions made
    *inside* the window, so a window containing no purchases produced a
    flat zero series and the overlay drew nothing at all — which is
    every window shorter than the age of the holdings, i.e. exactly the
    "1Y vs MSCI World" case for a portfolio bought years ago.
    """
    from app.models import PricePoint

    account = client.post(
        "/api/accounts",
        json={"name": "Depot", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    held = client.post(
        "/api/instruments",
        json={
            "name": "Long Held ETF", "isin": "XX0000000750", "asset_class": "EQUITY",
            "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    benchmark = client.post(
        "/api/instruments",
        json={
            "name": "Index", "isin": "XX0000000760", "asset_class": "EQUITY",
            "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]

    # Bought in 2023; the window we ask for starts in 2024, so the only
    # flow that exists predates it entirely.
    for instrument, marks in [
        (held, [(date(2023, 1, 1), "100.00"), (date(2024, 1, 1), "100.00"),
                (date(2024, 6, 1), "150.00")]),
        (benchmark, [(date(2023, 1, 1), "10.00"), (date(2024, 1, 1), "10.00"),
                     (date(2024, 6, 1), "12.00")]),
    ]:
        for d, close in marks:
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
            "external_id": "bench-old-buy", "date": "2023-01-01", "type": "BUY",
            "account_id": account, "instrument_id": held,
            "quantity": "10", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    client.post("/api/admin/rebuild-snapshots", headers=auth_headers)

    # "3Y" back from today lands well after the 2023-01-01 purchase, so
    # the window provably contains no flow at all. Anchoring on a
    # relative period rather than a literal date keeps this true as the
    # calendar moves.
    body = client.get(
        "/api/performance",
        params={
            "scope": "total", "period": "3Y", "method": "twr",
            "benchmark_instrument_id": benchmark,
        },
        headers=auth_headers,
    ).json()

    assert body["start_date"] > "2023-01-01", "window must exclude the only purchase"
    assert body["benchmark_curve"], "benchmark overlay must be drawn"
    # The index went 10 -> 12 over the window: +20%, so the shadow curve
    # ends at 120 having been seeded with the portfolio's opening value.
    assert body["benchmark_curve"][-1]["index_value"] == pytest.approx(120.0, abs=1e-6)
    # The portfolio itself went 100 -> 150: +50%, and beat the index.
    assert body["curve"][-1]["index_value"] == pytest.approx(150.0, abs=1e-6)


def test_benchmark_opening_value_is_not_double_counted_at_inception(
    client, auth_headers, db_session
):
    """At true inception nothing was held the day before, so seeding
    must contribute exactly zero — the opening position enters once, via
    its own flow."""
    from app.models import PricePoint

    account, instrument = _setup_scenario(client, auth_headers, db_session)
    benchmark = client.post(
        "/api/instruments",
        json={
            "name": "Index", "isin": "XX0000000770", "asset_class": "EQUITY",
            "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    for d, close in [(date(2024, 1, 1), "10.00"), (date(2024, 1, 20), "11.00")]:
        db_session.add(
            PricePoint(
                instrument_id=benchmark, date=d, close=Decimal(close),
                currency="EUR", provider="test", quality="ok",
            )
        )
    db_session.commit()

    body = client.get(
        "/api/performance",
        params={
            "scope": "total", "period": "inception", "method": "twr",
            "benchmark_instrument_id": benchmark,
        },
        headers=auth_headers,
    ).json()

    # 10 -> 11 is +10%, regardless of how the flows are scheduled: a
    # double-counted opening balance would distort this away from 110.
    assert body["benchmark_curve"][-1]["index_value"] == pytest.approx(110.0, abs=1e-6)


def test_benchmark_return_pct_matches_the_index_own_price_move(
    client, auth_headers, db_session
):
    """The headline comparison must be the benchmark's actual return, not
    something that drifts from it. A fully-invested shadow portfolio's
    chained return is exactly the index's price return over the window,
    whatever the portfolio it is drawn against did."""
    from app.models import PricePoint

    account = client.post(
        "/api/accounts",
        json={"name": "Depot", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    held = client.post(
        "/api/instruments",
        json={
            "name": "Held", "isin": "XX0000000780", "asset_class": "CRYPTO",
            "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    benchmark = client.post(
        "/api/instruments",
        json={
            "name": "Index", "isin": "XX0000000790", "asset_class": "EQUITY",
            "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]

    # The holding triples; the index doubles. Deliberately different, so
    # a benchmark figure that echoed the portfolio would be caught.
    for instrument, marks in [
        (held, [(date(2024, 1, 1), "100.00"), (date(2024, 6, 1), "300.00")]),
        (benchmark, [(date(2024, 1, 1), "10.00"), (date(2024, 6, 1), "20.00")]),
    ]:
        for d, close in marks:
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
            "external_id": "bret-buy", "date": "2024-01-01", "type": "BUY",
            "account_id": account, "instrument_id": held,
            "quantity": "10", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    client.post("/api/admin/rebuild-snapshots", headers=auth_headers)

    body = client.get(
        "/api/performance",
        params={
            "scope": "total", "period": "inception", "method": "twr",
            "benchmark_instrument_id": benchmark,
        },
        headers=auth_headers,
    ).json()

    assert body["return_pct"] == pytest.approx(2.0, abs=1e-9)           # +200%
    assert body["benchmark_return_pct"] == pytest.approx(1.0, abs=1e-9)  # +100%
    # And it agrees with the curve it is drawn beside, so the headline
    # figure and the chart can never tell different stories.
    assert body["benchmark_curve"][-1]["index_value"] == pytest.approx(200.0, abs=1e-6)


def test_benchmark_return_pct_absent_without_a_benchmark(client, auth_headers, db_session):
    _setup_scenario(client, auth_headers, db_session)
    body = client.get(
        "/api/performance",
        params={"scope": "total", "period": "inception", "method": "twr"},
        headers=auth_headers,
    ).json()
    assert body["benchmark_return_pct"] is None
