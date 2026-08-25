"""Per-instrument return ranking (spec 4.2: TWR/MWR "in total, per account
or per instrument").

The bulk helpers in performance_query.py exist purely for cost: computing
one row per instrument through the single-scope `value_series` /
`flow_events` / `inception_date` would re-scan the whole snapshot table
once per instrument, and `inception_date` in particular is unbounded by
date. The danger in having two paths is that they drift apart silently,
so most of this file is equivalence: the bulk form must agree with the
single-scope form it replaces, instrument by instrument.

Invented ISINs and quantities only, per AGENTS.md.
"""

from datetime import date
from decimal import Decimal

import pytest


def _setup_two_instruments(client, auth_headers, db_session):
    """Two market instruments in one account with different inceptions and
    opposite fortunes, so a ranking has something to rank.

    ETF A: BUY 10 @ 100 on 2023-11-01, price 100 -> 150 by 2024-06-01.
    ETF B: BUY 20 @ 50 on 2024-02-01, price 50 -> 40 by 2024-06-01.
    """
    from app.models import PricePoint

    account = client.post(
        "/api/accounts",
        json={"name": "Depot", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]

    ids = {}
    for name, isin in [("ETF A", "XX0000000700"), ("ETF B", "XX0000000701")]:
        ids[name] = client.post(
            "/api/instruments",
            json={
                "name": name, "isin": isin, "asset_class": "EQUITY",
                "valuation_mode": "MARKET", "currency": "EUR",
            },
            headers=auth_headers,
        ).json()["id"]

    prices = [
        (ids["ETF A"], date(2023, 11, 1), "100.00"),
        (ids["ETF A"], date(2024, 1, 1), "120.00"),
        (ids["ETF A"], date(2024, 6, 1), "150.00"),
        (ids["ETF B"], date(2024, 2, 1), "50.00"),
        (ids["ETF B"], date(2024, 6, 1), "40.00"),
    ]
    for instrument_id, d, close in prices:
        db_session.add(
            PricePoint(
                instrument_id=instrument_id, date=d, close=Decimal(close),
                currency="EUR", provider="test", quality="ok",
            )
        )
    db_session.commit()

    client.post(
        "/api/transactions",
        json={
            "external_id": "bi-buy-a", "date": "2023-11-01", "type": "BUY",
            "account_id": account, "instrument_id": ids["ETF A"],
            "quantity": "10", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    client.post(
        "/api/transactions",
        json={
            "external_id": "bi-buy-b", "date": "2024-02-01", "type": "BUY",
            "account_id": account, "instrument_id": ids["ETF B"],
            "quantity": "20", "price": "50.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    client.post("/api/admin/rebuild-snapshots", headers=auth_headers)
    return account, ids


# --- equivalence with the single-scope path -------------------------------


def test_inception_dates_by_instrument_matches_single_scope(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.performance_query import (
        ScopeFilter,
        inception_date,
        inception_dates_by_instrument,
    )

    _, ids = _setup_two_instruments(client, auth_headers, db_session)

    db = SessionLocal()
    try:
        bulk = inception_dates_by_instrument(db, ScopeFilter())
        for instrument_id in ids.values():
            single = inception_date(db, ScopeFilter(instrument_id=instrument_id))
            assert bulk[instrument_id] == single
    finally:
        db.close()

    assert bulk[ids["ETF A"]] == date(2023, 11, 1)
    assert bulk[ids["ETF B"]] == date(2024, 2, 1)


def test_inception_dates_returns_real_dates_not_strings(client, auth_headers, db_session):
    """SQLite hands back a bare string for an aggregate over a Date column
    unless the type propagates. Compared against a `date` that silently
    reads as "not equal" rather than raising, so it is asserted outright."""
    from app.database import SessionLocal
    from app.performance_query import ScopeFilter, inception_dates_by_instrument

    _setup_two_instruments(client, auth_headers, db_session)

    db = SessionLocal()
    try:
        bulk = inception_dates_by_instrument(db, ScopeFilter())
    finally:
        db.close()
    assert bulk
    assert all(isinstance(d, date) for d in bulk.values())


def test_value_series_by_instrument_matches_single_scope(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.performance_query import (
        ScopeFilter,
        value_series,
        value_series_by_instrument,
    )

    _, ids = _setup_two_instruments(client, auth_headers, db_session)
    start, end = date(2023, 10, 1), date(2024, 6, 1)

    db = SessionLocal()
    try:
        bulk = value_series_by_instrument(db, ScopeFilter(), start, end)
        for instrument_id in ids.values():
            single = value_series(
                db, ScopeFilter(instrument_id=instrument_id), start, end
            )
            assert bulk[instrument_id] == single
    finally:
        db.close()


def test_flow_events_by_instrument_matches_single_scope(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.performance_query import (
        ScopeFilter,
        flow_events,
        flow_events_by_instrument,
    )

    _, ids = _setup_two_instruments(client, auth_headers, db_session)
    start, end = date(2023, 10, 1), date(2024, 6, 1)

    db = SessionLocal()
    try:
        bulk = flow_events_by_instrument(db, ScopeFilter(), start, end)
        for instrument_id in ids.values():
            single = flow_events(
                db, ScopeFilter(instrument_id=instrument_id), start, end
            )
            assert [(f.date, f.amount) for f in bulk.get(instrument_id, [])] == [
                (f.date, f.amount) for f in single
            ]
    finally:
        db.close()


def test_bulk_helpers_respect_the_asset_class_filter(client, auth_headers, db_session):
    """The filter must reach values, flows and inception alike — the same
    reasoning `_market_instrument_ids` carries for the single-scope path."""
    from app.database import SessionLocal
    from app.models import AssetClass
    from app.performance_query import (
        ScopeFilter,
        flow_events_by_instrument,
        inception_dates_by_instrument,
        value_series_by_instrument,
    )

    _setup_two_instruments(client, auth_headers, db_session)
    crypto_only = ScopeFilter(asset_classes=frozenset({AssetClass.CRYPTO}))

    db = SessionLocal()
    try:
        assert inception_dates_by_instrument(db, crypto_only) == {}
        assert value_series_by_instrument(
            db, crypto_only, date(2024, 1, 1), date(2024, 6, 1)
        ) == {}
        assert flow_events_by_instrument(
            db, crypto_only, date(2024, 1, 1), date(2024, 6, 1)
        ) == {}
    finally:
        db.close()


# --- the endpoint ---------------------------------------------------------


def test_by_instrument_ranks_every_market_instrument(client, auth_headers, db_session):
    _, ids = _setup_two_instruments(client, auth_headers, db_session)

    resp = client.get(
        "/api/performance/by-instrument",
        params={"period": "inception", "method": "twr"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["method"] == "twr"
    by_id = {row["instrument_id"]: row for row in body["instruments"]}
    assert set(by_id) == set(ids.values())

    # ETF A rose 100 -> 150 with no flows after the opening buy: +50%.
    assert by_id[ids["ETF A"]]["return_pct"] == pytest.approx(0.50, abs=1e-6)
    # ETF B fell 50 -> 40: -20%.
    assert by_id[ids["ETF B"]]["return_pct"] == pytest.approx(-0.20, abs=1e-6)
    # Sorted best first, so the table has a defined order before the
    # client touches it.
    assert body["instruments"][0]["instrument_id"] == ids["ETF A"]


def test_by_instrument_agrees_with_the_single_scope_endpoint(client, auth_headers, db_session):
    """The whole point of the batch endpoint is to be the same numbers,
    cheaper. If it ever disagrees with ?scope=instrument:N, one of them is
    lying and the ranking is the one nobody would check by hand."""
    _, ids = _setup_two_instruments(client, auth_headers, db_session)

    for method in ("twr", "mwr"):
        batch = client.get(
            "/api/performance/by-instrument",
            params={"period": "1Y", "method": method},
            headers=auth_headers,
        ).json()
        by_id = {row["instrument_id"]: row for row in batch["instruments"]}

        for instrument_id in ids.values():
            single = client.get(
                "/api/performance",
                params={
                    "scope": f"instrument:{instrument_id}",
                    "period": "1Y",
                    "method": method,
                },
                headers=auth_headers,
            ).json()
            batch_pct = by_id[instrument_id]["return_pct"]
            if single["return_pct"] is None:
                assert batch_pct is None
            else:
                assert batch_pct == pytest.approx(single["return_pct"], abs=1e-9)


def test_by_instrument_reports_each_instruments_own_inception(client, auth_headers, db_session):
    _, ids = _setup_two_instruments(client, auth_headers, db_session)

    body = client.get(
        "/api/performance/by-instrument",
        params={"period": "inception", "method": "twr"},
        headers=auth_headers,
    ).json()
    by_id = {row["instrument_id"]: row for row in body["instruments"]}

    # ETF B did not exist when ETF A started; its row must not claim a
    # window reaching back before it was bought.
    assert by_id[ids["ETF A"]]["start_date"] == "2023-11-01"
    assert by_id[ids["ETF B"]]["start_date"] == "2024-02-01"


def test_by_instrument_carries_current_value_for_context(client, auth_headers, db_session):
    """A +400% return on 50 EUR is noise. The ranking is only readable
    next to what each position is actually worth."""
    _, ids = _setup_two_instruments(client, auth_headers, db_session)

    body = client.get(
        "/api/performance/by-instrument",
        params={"period": "inception", "method": "twr"},
        headers=auth_headers,
    ).json()
    by_id = {row["instrument_id"]: row for row in body["instruments"]}
    assert Decimal(by_id[ids["ETF A"]]["value_eur"]) == Decimal("1500.00")
    assert Decimal(by_id[ids["ETF B"]]["value_eur"]) == Decimal("800.00")


def test_by_instrument_honours_the_asset_class_filter(client, auth_headers, db_session):
    _setup_two_instruments(client, auth_headers, db_session)

    body = client.get(
        "/api/performance/by-instrument",
        params={"period": "inception", "method": "twr", "asset_classes": "CRYPTO"},
        headers=auth_headers,
    ).json()
    assert body["instruments"] == []


def test_by_instrument_rejects_a_bad_method(client, auth_headers, db_session):
    _setup_two_instruments(client, auth_headers, db_session)
    resp = client.get(
        "/api/performance/by-instrument",
        params={"period": "1Y", "method": "sharpe"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_method"


def test_by_instrument_rejects_a_bad_period(client, auth_headers, db_session):
    _setup_two_instruments(client, auth_headers, db_session)
    resp = client.get(
        "/api/performance/by-instrument",
        params={"period": "10Y", "method": "twr"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_period"


def test_by_instrument_on_an_empty_database_is_empty_not_an_error(client, auth_headers):
    resp = client.get(
        "/api/performance/by-instrument",
        params={"period": "1Y", "method": "twr"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["instruments"] == []


def test_response_carries_the_common_window_for_comparison(client, auth_headers, db_session):
    """A row's own start_date only means something next to the window that
    was actually asked for. Without this, every row repeating the same
    date is indistinguishable from every row being clipped."""
    _, ids = _setup_two_instruments(client, auth_headers, db_session)

    body = client.get(
        "/api/performance/by-instrument",
        params={"period": "inception", "method": "twr"},
        headers=auth_headers,
    ).json()
    by_id = {row["instrument_id"]: row for row in body["instruments"]}

    # Since inception, the common window opens at the earliest holding.
    assert body["start_date"] == "2023-11-01"
    # ETF A is that holding, so its row is not clipped; ETF B is.
    assert by_id[ids["ETF A"]]["start_date"] == body["start_date"]
    assert by_id[ids["ETF B"]]["start_date"] > body["start_date"]


def test_a_holding_younger_than_the_window_still_matches_single_scope(
    client, auth_headers, db_session
):
    """The case the equivalence test above cannot reach.

    `?scope=instrument:N` clamps its window start up to that instrument's
    own inception; the batch path keeps the common window start for every
    row instead. For TWR that is provably the same figure (the leading
    days have a zero base and `daily_returns` skips those). For MWR it is
    the same only because the implicit opening cashflow is zero, and a
    zero-amount cashflow shifts `xirr`'s `d0` without moving the root —
    every exponent changes by one constant, which factors out.

    That is a real argument, not an obvious one, and nothing else in this
    suite exercises it. A future change to either path that breaks it
    would otherwise surface as a wrong number in a ranking nobody
    recomputes by hand.
    """
    from datetime import timedelta

    from app.models import PricePoint

    account, _ = _setup_two_instruments(client, auth_headers, db_session)

    # Bought well inside a one-year window, so `period=1Y` asks for more
    # history than this instrument has.
    bought = date.today() - timedelta(days=90)
    newcomer = client.post(
        "/api/instruments",
        json={
            "name": "ETF C", "isin": "XX0000000702", "asset_class": "EQUITY",
            "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    for d, close in [(bought, "20.00"), (date.today(), "26.00")]:
        db_session.add(
            PricePoint(
                instrument_id=newcomer, date=d, close=Decimal(close),
                currency="EUR", provider="test", quality="ok",
            )
        )
    db_session.commit()
    client.post(
        "/api/transactions",
        json={
            "external_id": "bi-buy-c", "date": bought.isoformat(), "type": "BUY",
            "account_id": account, "instrument_id": newcomer,
            "quantity": "25", "price": "20.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    client.post("/api/admin/rebuild-snapshots", headers=auth_headers)

    for method in ("twr", "mwr"):
        batch = client.get(
            "/api/performance/by-instrument",
            params={"period": "1Y", "method": method},
            headers=auth_headers,
        ).json()
        row = next(
            r for r in batch["instruments"] if r["instrument_id"] == newcomer
        )
        # The row reports its own shorter window, not the one that was asked
        # for — and the response says what was asked for, so the difference
        # is visible rather than implied.
        assert row["start_date"] == bought.isoformat()
        assert batch["start_date"] < row["start_date"]

        single = client.get(
            "/api/performance",
            params={
                "scope": f"instrument:{newcomer}", "period": "1Y", "method": method,
            },
            headers=auth_headers,
        ).json()
        assert single["start_date"] == bought.isoformat()
        assert row["return_pct"] == pytest.approx(single["return_pct"], abs=1e-9)
