from datetime import date
from decimal import Decimal


def test_cpi_endpoint_upsert_and_list(client, auth_headers):
    resp = client.post(
        "/api/cpi", json={"date": "2020-01-01", "index_value": "100.0"}, headers=auth_headers
    )
    assert resp.status_code == 201
    resp = client.post(
        "/api/cpi", json={"date": "2024-01-01", "index_value": "120.0"}, headers=auth_headers
    )
    assert resp.status_code == 201

    resp = client.get("/api/cpi", headers=auth_headers)
    assert resp.status_code == 200
    assert [p["date"] for p in resp.json()] == ["2020-01-01", "2024-01-01"]

    # Upsert: re-posting the same date updates rather than duplicating.
    resp = client.post(
        "/api/cpi", json={"date": "2020-01-01", "index_value": "101.0"}, headers=auth_headers
    )
    assert resp.status_code == 201
    resp = client.get("/api/cpi", headers=auth_headers)
    assert len(resp.json()) == 2
    assert resp.json()[0]["index_value"] == "101.0"


def test_cpi_endpoint_requires_write_scope(client, readonly_headers):
    resp = client.post(
        "/api/cpi", json={"date": "2020-01-01", "index_value": "100.0"}, headers=readonly_headers
    )
    assert resp.status_code == 403


def test_networth_timeseries_real_flag_deflates_values(client, auth_headers, db_session):
    from app.models import DailySnapshot

    db_session.add(
        DailySnapshot(
            date=date(2020, 6, 1), scope_type="total", scope_id="investable",
            value_eur=Decimal("1000.00"),
        )
    )
    db_session.add(
        DailySnapshot(
            date=date(2024, 6, 1), scope_type="total", scope_id="investable",
            value_eur=Decimal("1200.00"),
        )
    )
    db_session.commit()
    client.post("/api/cpi", json={"date": "2020-01-01", "index_value": "100.0"}, headers=auth_headers)
    client.post("/api/cpi", json={"date": "2024-01-01", "index_value": "120.0"}, headers=auth_headers)

    resp = client.get(
        "/api/timeseries/networth", params={"real": "true"}, headers=auth_headers
    )
    assert resp.status_code == 200
    points = {p["date"]: p["value_eur"] for p in resp.json()}
    assert Decimal(points["2020-06-01"]) == Decimal(1200)  # 1000 * 120/100
    assert points["2024-06-01"] == "1200.00"   # already at latest CPI


def test_networth_timeseries_without_real_flag_stays_nominal(client, auth_headers, db_session):
    from app.models import DailySnapshot

    db_session.add(
        DailySnapshot(
            date=date(2020, 6, 1), scope_type="total", scope_id="investable",
            value_eur=Decimal("1000.00"),
        )
    )
    db_session.commit()
    client.post("/api/cpi", json={"date": "2020-01-01", "index_value": "100.0"}, headers=auth_headers)
    client.post("/api/cpi", json={"date": "2024-01-01", "index_value": "120.0"}, headers=auth_headers)

    resp = client.get("/api/timeseries/networth", headers=auth_headers)
    assert resp.json()[0]["value_eur"] == "1000.00"
