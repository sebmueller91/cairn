"""Bug 5 (and the query-param edges of bugs 2/3/4): query parameters that
used to be silently ignored or coerced into a wrong-looking-but-200
response instead of being rejected. Each of these produced a card that
looked like "no data" rather than an error, which is worse than a crash
because it's indistinguishable from a portfolio that's genuinely empty.

Invented ISINs, quantities and amounts only, per AGENTS.md.
"""

from datetime import date
from decimal import Decimal


def _seed_networth_snapshots(db_session):
    from app.models import DailySnapshot

    # Two full years, one point per quarter, so day/month/quarter/year
    # granularities are all distinguishable from each other by both point
    # count and which value survives the downsample.
    points = [
        (date(2023, 1, 15), "100.00"),
        (date(2023, 4, 15), "110.00"),
        (date(2023, 7, 15), "120.00"),
        (date(2023, 10, 15), "130.00"),
        (date(2024, 1, 15), "140.00"),
        (date(2024, 4, 15), "150.00"),
    ]
    for day, value in points:
        db_session.add(
            DailySnapshot(
                date=day, scope_type="total", scope_id="investable", value_eur=Decimal(value)
            )
        )
    db_session.commit()
    return points


# --- /api/timeseries/networth ---


def test_networth_bogus_granularity_is_rejected(client, auth_headers, db_session):
    _seed_networth_snapshots(db_session)
    resp = client.get(
        "/api/timeseries/networth", params={"granularity": "bogus"}, headers=auth_headers
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_granularity"


def test_networth_quarter_granularity_downsamples(client, auth_headers, db_session):
    _seed_networth_snapshots(db_session)
    resp = client.get(
        "/api/timeseries/networth", params={"granularity": "quarter"}, headers=auth_headers
    )
    assert resp.status_code == 200
    points = resp.json()
    # 6 daily rows across 6 distinct quarters -> one point per quarter, not
    # the full 6-row daily series unchanged.
    assert len(points) == 6
    assert points[0]["date"] == "2023-01-15"
    assert points[0]["value_eur"] == "100.00"


def test_networth_year_granularity_downsamples(client, auth_headers, db_session):
    _seed_networth_snapshots(db_session)
    resp = client.get(
        "/api/timeseries/networth", params={"granularity": "year"}, headers=auth_headers
    )
    assert resp.status_code == 200
    points = resp.json()
    # 2023 has 4 rows -> last one (Oct 15) represents the year; 2024 has 2
    # rows -> last one (Apr 15). Two points total, not six.
    assert [p["date"] for p in points] == ["2023-10-15", "2024-04-15"]
    assert [p["value_eur"] for p in points] == ["130.00", "150.00"]


def test_networth_bogus_scope_is_rejected(client, auth_headers, db_session):
    _seed_networth_snapshots(db_session)
    resp = client.get(
        "/api/timeseries/networth", params={"scope": "bogus"}, headers=auth_headers
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_scope"


def test_networth_scope_total_is_rejected_not_silently_empty(client, auth_headers, db_session):
    # "total" reads like the obvious name for "everything", but
    # snapshot_service only ever writes investable/gross/net scope_ids —
    # it used to silently return [] instead of naming the real values.
    _seed_networth_snapshots(db_session)
    resp = client.get(
        "/api/timeseries/networth", params={"scope": "total"}, headers=auth_headers
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_scope"


def test_networth_from_after_to_is_rejected(client, auth_headers, db_session):
    _seed_networth_snapshots(db_session)
    resp = client.get(
        "/api/timeseries/networth",
        params={"from": "2024-01-01", "to": "2023-01-01"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_range"


# --- /api/timeseries/allocation ---


def test_allocation_timeseries_bogus_granularity_is_rejected(client, auth_headers):
    resp = client.get(
        "/api/timeseries/allocation", params={"granularity": "bogus"}, headers=auth_headers
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_granularity"


def test_allocation_timeseries_from_after_to_is_rejected(client, auth_headers):
    resp = client.get(
        "/api/timeseries/allocation",
        params={"from": "2024-01-01", "to": "2023-01-01"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_range"


# --- /api/positions ---


def test_positions_bogus_group_by_is_rejected(client, auth_headers):
    resp = client.get("/api/positions", params={"group_by": "bogus"}, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_group_by"


# --- /api/look-through ---


def test_look_through_bogus_dimension_is_rejected(client, auth_headers):
    resp = client.get("/api/look-through", params={"dimension": "bogus"}, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_dimension"


# --- /api/milestones ---


def test_milestones_bogus_scope_is_rejected(client, auth_headers):
    resp = client.get("/api/milestones", params={"scope": "bogus"}, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_scope"


# --- Bug 2: /api/tax?year out of range, and year=0 falsy trap ---


def test_tax_year_far_future_is_rejected_not_500(client, auth_headers):
    resp = client.get("/api/tax", params={"year": 99999}, headers=auth_headers)
    assert resp.status_code < 500
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_year"


def test_tax_year_just_above_max_is_rejected_not_500(client, auth_headers):
    resp = client.get("/api/tax", params={"year": 10000}, headers=auth_headers)
    assert resp.status_code < 500
    assert resp.json()["detail"]["code"] == "invalid_year"


def test_tax_year_negative_is_rejected_not_500(client, auth_headers):
    resp = client.get("/api/tax", params={"year": -1}, headers=auth_headers)
    assert resp.status_code < 500
    assert resp.json()["detail"]["code"] == "invalid_year"


def test_tax_year_zero_does_not_silently_become_current_year(client, auth_headers):
    # `year or date.today().year` treated 0 as falsy and silently used the
    # current year instead of the explicitly requested (out-of-range) 0.
    resp = client.get("/api/tax", params={"year": 0}, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_year"
    assert resp.json()["detail"]["params"]["year"] == 0


def test_tax_omitted_year_still_defaults_to_current_year(client, auth_headers):
    # The None-check fix must not break the legitimate default path.
    resp = client.get("/api/tax", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["saver_allowance"]["year"] == date.today().year


# --- Bug 3: /api/allocation?contribution non-finite values ---


def test_allocation_contribution_nan_is_rejected_not_500(client, auth_headers):
    resp = client.get("/api/allocation", params={"contribution": "nan"}, headers=auth_headers)
    assert resp.status_code < 500
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_contribution"


def test_allocation_contribution_capitalized_nan_is_rejected_not_500(client, auth_headers):
    resp = client.get("/api/allocation", params={"contribution": "NaN"}, headers=auth_headers)
    assert resp.status_code < 500
    assert resp.json()["detail"]["code"] == "invalid_contribution"


def test_allocation_contribution_infinity_is_rejected(client, auth_headers):
    resp = client.get(
        "/api/allocation", params={"contribution": "Infinity"}, headers=auth_headers
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_contribution"


def test_allocation_contribution_negative_infinity_is_rejected(client, auth_headers):
    resp = client.get(
        "/api/allocation", params={"contribution": "-Infinity"}, headers=auth_headers
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_contribution"


def test_allocation_contribution_implausible_exponent_is_rejected(client, auth_headers):
    resp = client.get(
        "/api/allocation", params={"contribution": "1e100000"}, headers=auth_headers
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_contribution"


def test_allocation_contribution_normal_amount_still_works(client, auth_headers):
    resp = client.get("/api/allocation", params={"contribution": "1000"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["rebalance_purchases_only"] is not None


# --- Bug 4: duplicate ISIN on POST /api/instruments ---


def test_duplicate_isin_is_rejected_not_500(client, auth_headers):
    payload = {
        "name": "First ETF",
        "isin": "XX0000009900",
        "asset_class": "EQUITY",
        "valuation_mode": "MARKET",
        "currency": "EUR",
    }
    first = client.post("/api/instruments", json=payload, headers=auth_headers)
    assert first.status_code == 201

    duplicate = {**payload, "name": "Second ETF"}
    second = client.post("/api/instruments", json=duplicate, headers=auth_headers)
    assert second.status_code < 500
    assert second.status_code == 409
    body = second.json()
    assert body["detail"]["code"] == "instrument_isin_exists"
    assert body["detail"]["params"]["isin"] == "XX0000009900"
