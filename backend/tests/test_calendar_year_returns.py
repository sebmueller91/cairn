"""Calendar-year return table — the DB-facing half. The year-boundary
arithmetic itself is unit-tested without a database in
test_calendar_year_slices.py; this file checks the endpoint assembles
real ledger data into it correctly.

Invented ISINs and quantities only, per AGENTS.md.
"""

from datetime import date
from decimal import Decimal

import pytest


def _setup_two_calendar_years(client, auth_headers, db_session):
    """One holding spanning a year boundary, bought mid-2023.

    Price: 100 on 2023-07-01 (purchase), 200 on 2023-12-31, 300 on
    2024-06-30. So 2023 returns +100% (from the purchase, a partial year)
    and 2024 returns +50% (200 -> 300, also partial — the window ends at
    the last snapshot).
    """
    from app.models import PricePoint

    account = client.post(
        "/api/accounts",
        json={"name": "Depot", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Year ETF", "isin": "XX0000000800", "asset_class": "EQUITY",
            "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]

    for d, close in [
        (date(2023, 7, 1), "100.00"),
        (date(2023, 12, 31), "200.00"),
        (date(2024, 6, 30), "300.00"),
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
            "external_id": "cy-buy-1", "date": "2023-07-01", "type": "BUY",
            "account_id": account, "instrument_id": instrument,
            "quantity": "10", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    client.post("/api/admin/rebuild-snapshots", headers=auth_headers)
    return account, instrument


def test_one_row_per_calendar_year_since_inception(client, auth_headers, db_session):
    """Every year from inception to now, with no gaps. The series runs to
    today, not to the last price: the snapshot engine carries a held
    position forward, so the years after the last price move are real
    years of holding it — flat, but held. (Stale prices are the data
    quality panel's job to surface, not this endpoint's.)"""
    _setup_two_calendar_years(client, auth_headers, db_session)

    resp = client.get("/api/performance/calendar-years", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["method"] == "twr"

    years = [row["year"] for row in body["years"]]
    assert years[0] == 2023
    assert years[-1] == date.today().year
    assert years == list(range(years[0], years[-1] + 1))


def test_year_returns_are_measured_across_the_boundary(client, auth_headers, db_session):
    """2024's return must start from 31 December 2023's close, not from
    its own first snapshot — otherwise the New Year's move belongs to no
    year at all."""
    _setup_two_calendar_years(client, auth_headers, db_session)

    body = client.get("/api/performance/calendar-years", headers=auth_headers).json()
    by_year = {row["year"]: row for row in body["years"]}

    assert by_year[2023]["return_pct"] == pytest.approx(1.0, abs=1e-6)
    assert by_year[2024]["return_pct"] == pytest.approx(0.5, abs=1e-6)


def test_chained_years_reproduce_the_since_inception_return(client, auth_headers, db_session):
    """The identity that makes the table trustworthy: multiply the yearly
    figures together and you must land on what ?period=inception says."""
    _setup_two_calendar_years(client, auth_headers, db_session)

    years = client.get("/api/performance/calendar-years", headers=auth_headers).json()["years"]
    overall = client.get(
        "/api/performance",
        params={"scope": "total", "period": "inception", "method": "twr"},
        headers=auth_headers,
    ).json()["return_pct"]

    chained = 1.0
    for row in years:
        if row["return_pct"] is not None:
            chained *= 1.0 + row["return_pct"]
    assert chained - 1.0 == pytest.approx(overall, abs=1e-6)


def test_incomplete_years_are_flagged_as_partial(client, auth_headers, db_session):
    """A year clipped at either end must say so. Rendering a seven-month
    stub as a plain annual return invites comparison with a full year."""
    _setup_two_calendar_years(client, auth_headers, db_session)

    body = client.get("/api/performance/calendar-years", headers=auth_headers).json()
    by_year = {row["year"]: row for row in body["years"]}

    # 2023 is clipped at the near end by the purchase date.
    assert by_year[2023]["partial"] is True
    assert by_year[2023]["start_date"] == "2023-07-01"
    assert by_year[2023]["end_date"] == "2023-12-31"

    # The current year is clipped at the far end by the last snapshot.
    current = by_year[date.today().year]
    assert current["partial"] is True
    assert current["start_date"] == f"{date.today().year}-01-01"


def test_a_fully_covered_year_is_not_flagged_partial(client, auth_headers, db_session):
    _setup_two_calendar_years(client, auth_headers, db_session)

    body = client.get("/api/performance/calendar-years", headers=auth_headers).json()
    by_year = {row["year"]: row for row in body["years"]}

    assert by_year[2024]["partial"] is False
    assert by_year[2024]["start_date"] == "2024-01-01"
    assert by_year[2024]["end_date"] == "2024-12-31"


def test_benchmark_column_uses_the_same_shadow_portfolio(client, auth_headers, db_session):
    """Same convention as the chart overlay: "what if every contribution
    had gone into this instead", not the benchmark's raw price return —
    so the table and the chart can never disagree."""
    from app.models import PricePoint

    _setup_two_calendar_years(client, auth_headers, db_session)

    benchmark = client.post(
        "/api/instruments",
        json={
            "name": "World ETF", "isin": "XX0000000801", "asset_class": "EQUITY",
            "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    # +25% during 2023 after the purchase, then +20% during 2024.
    for d, close in [
        (date(2023, 7, 1), "80.00"),
        (date(2023, 12, 31), "100.00"),
        (date(2024, 6, 30), "120.00"),
    ]:
        db_session.add(
            PricePoint(
                instrument_id=benchmark, date=d, close=Decimal(close),
                currency="EUR", provider="test", quality="ok",
            )
        )
    db_session.commit()

    body = client.get(
        "/api/performance/calendar-years",
        params={"benchmark_instrument_id": benchmark},
        headers=auth_headers,
    ).json()
    by_year = {row["year"]: row for row in body["years"]}

    assert by_year[2023]["benchmark_return_pct"] == pytest.approx(0.25, abs=1e-6)
    assert by_year[2024]["benchmark_return_pct"] == pytest.approx(0.20, abs=1e-6)


def test_no_benchmark_column_when_none_requested(client, auth_headers, db_session):
    _setup_two_calendar_years(client, auth_headers, db_session)
    body = client.get("/api/performance/calendar-years", headers=auth_headers).json()
    assert all(row["benchmark_return_pct"] is None for row in body["years"])


def test_scope_narrows_to_one_account(client, auth_headers, db_session):
    account, _ = _setup_two_calendar_years(client, auth_headers, db_session)

    resp = client.get(
        "/api/performance/calendar-years",
        params={"scope": f"account:{account}"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    years = [row["year"] for row in resp.json()["years"]]
    assert years[0] == 2023 and years[-1] == date.today().year

    empty = client.post(
        "/api/accounts",
        json={"name": "Empty", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    resp = client.get(
        "/api/performance/calendar-years",
        params={"scope": f"account:{empty}"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["years"] == []


def test_rejects_a_bad_scope(client, auth_headers, db_session):
    _setup_two_calendar_years(client, auth_headers, db_session)
    resp = client.get(
        "/api/performance/calendar-years",
        params={"scope": "portfolio:1"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_scope"


def test_empty_database_yields_no_years(client, auth_headers):
    resp = client.get("/api/performance/calendar-years", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["years"] == []
