from datetime import date
from decimal import Decimal


def test_rebuild_snapshots_endpoint(client, auth_headers, db_session):
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
            "isin": "XX0000000210",
            "asset_class": "EQUITY",
            "valuation_mode": "MARKET",
            "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    client.post(
        "/api/transactions",
        json={
            "external_id": "ts-buy-1",
            "date": "2024-01-01",
            "type": "BUY",
            "account_id": account,
            "instrument_id": instrument,
            "quantity": "1",
            "price": "50.00",
            "currency": "EUR",
        },
        headers=auth_headers,
    )
    db_session.add(
        PricePoint(
            instrument_id=instrument,
            date=date(2024, 1, 1),
            close=Decimal("50.00"),
            currency="EUR",
            provider="stooq",
            quality="ok",
        )
    )
    db_session.commit()

    rebuild = client.post("/api/admin/rebuild-snapshots", headers=auth_headers)
    assert rebuild.status_code == 200
    assert rebuild.json()["days_written"] > 0

    health = client.get("/api/health").json()
    assert health["last_snapshot"] is not None

    daily = client.get(
        "/api/timeseries/networth",
        params={"from": "2024-01-01", "to": "2024-01-01", "granularity": "day"},
        headers=auth_headers,
    )
    assert daily.status_code == 200
    assert daily.json()[0]["value_eur"] == "50.00"


def test_networth_timeseries_requires_auth(client):
    resp = client.get("/api/timeseries/networth")
    assert resp.status_code == 401


def test_networth_downsampling_to_month(client, auth_headers, db_session):
    from app.models import DailySnapshot

    for day, value in [
        (date(2024, 1, 5), "100.00"),
        (date(2024, 1, 20), "110.00"),
        (date(2024, 2, 3), "120.00"),
        (date(2024, 2, 15), "130.00"),
    ]:
        db_session.add(
            DailySnapshot(
                date=day, scope_type="total", scope_id="investable", value_eur=Decimal(value)
            )
        )
    db_session.commit()

    resp = client.get(
        "/api/timeseries/networth", params={"granularity": "month"}, headers=auth_headers
    )
    points = resp.json()
    assert len(points) == 2
    assert points[0]["date"] == "2024-01-20"  # last point in January
    assert points[0]["value_eur"] == "110.00"
    assert points[1]["date"] == "2024-02-15"
