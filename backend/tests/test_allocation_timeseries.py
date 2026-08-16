from datetime import date
from decimal import Decimal


def _seed_instrument(db_session, asset_class, valuation_mode="MARKET"):
    from app.models import Instrument

    instrument = Instrument(
        name=f"Test {asset_class}",
        asset_class=asset_class,
        valuation_mode=valuation_mode,
        currency="EUR",
    )
    db_session.add(instrument)
    db_session.commit()
    db_session.refresh(instrument)
    return instrument


def test_allocation_timeseries_groups_by_class(client, auth_headers, db_session):
    from app.models import DailySnapshot

    equity = _seed_instrument(db_session, "EQUITY")
    crypto = _seed_instrument(db_session, "CRYPTO")

    db_session.add_all(
        [
            DailySnapshot(
                date=date(2024, 1, 5),
                scope_type="position",
                scope_id=f"1:{equity.id}",
                value_eur=Decimal("100.00"),
            ),
            DailySnapshot(
                date=date(2024, 1, 5),
                scope_type="position",
                scope_id=f"1:{crypto.id}",
                value_eur=Decimal("50.00"),
            ),
            DailySnapshot(
                date=date(2024, 1, 5),
                scope_type="cash_account",
                scope_id="2",
                value_eur=Decimal("25.00"),
            ),
            DailySnapshot(
                date=date(2024, 1, 5),
                scope_type="loan",
                scope_id="3",
                value_eur=Decimal("-40.00"),
            ),
        ]
    )
    db_session.commit()

    resp = client.get("/api/timeseries/allocation", headers=auth_headers)
    assert resp.status_code == 200
    points = resp.json()
    assert len(points) == 1
    point = points[0]
    assert point["date"] == "2024-01-05"
    assert point["values"] == {
        "EQUITY": "100.00",
        "CRYPTO": "50.00",
        "CASH": "25.00",
        "LIABILITY": "-40.00",
    }
    # values must be strings, not JSON numbers
    for v in point["values"].values():
        assert isinstance(v, str)


def test_allocation_timeseries_downsamples_to_month(client, auth_headers, db_session):
    from app.models import DailySnapshot

    equity = _seed_instrument(db_session, "EQUITY")

    db_session.add_all(
        [
            DailySnapshot(
                date=date(2024, 1, 5),
                scope_type="position",
                scope_id=f"1:{equity.id}",
                value_eur=Decimal("100.00"),
            ),
            DailySnapshot(
                date=date(2024, 1, 20),
                scope_type="position",
                scope_id=f"1:{equity.id}",
                value_eur=Decimal("110.00"),
            ),
            DailySnapshot(
                date=date(2024, 2, 3),
                scope_type="position",
                scope_id=f"1:{equity.id}",
                value_eur=Decimal("120.00"),
            ),
            DailySnapshot(
                date=date(2024, 2, 15),
                scope_type="position",
                scope_id=f"1:{equity.id}",
                value_eur=Decimal("130.00"),
            ),
        ]
    )
    db_session.commit()

    resp = client.get(
        "/api/timeseries/allocation", params={"granularity": "month"}, headers=auth_headers
    )
    points = resp.json()
    assert len(points) == 2
    assert points[0]["date"] == "2024-01-20"
    assert points[0]["values"] == {"EQUITY": "110.00"}
    assert points[1]["date"] == "2024-02-15"
    assert points[1]["values"] == {"EQUITY": "130.00"}


def test_allocation_timeseries_matches_networth_invariant(client, auth_headers, db_session):
    """The sum across all classes on a date must equal the /networth net
    total on that same date — this is what makes the frontend's "all
    classes selected" filtered sum equal net worth."""
    from app.models import DailySnapshot

    equity = _seed_instrument(db_session, "EQUITY")
    house = _seed_instrument(db_session, "REAL_ESTATE", valuation_mode="ANCHORED")

    d = date(2024, 3, 1)
    db_session.add_all(
        [
            DailySnapshot(
                date=d, scope_type="position", scope_id=f"1:{equity.id}", value_eur=Decimal("300.00")
            ),
            DailySnapshot(
                date=d, scope_type="position", scope_id=f"1:{house.id}", value_eur=Decimal("500.00")
            ),
            DailySnapshot(
                date=d, scope_type="cash_account", scope_id="2", value_eur=Decimal("100.00")
            ),
            DailySnapshot(date=d, scope_type="loan", scope_id="3", value_eur=Decimal("-150.00")),
            # net total snapshot, matching the sum above: 300+500+100-150 = 750
            DailySnapshot(date=d, scope_type="total", scope_id="net", value_eur=Decimal("750.00")),
        ]
    )
    db_session.commit()

    alloc_resp = client.get("/api/timeseries/allocation", headers=auth_headers)
    net_resp = client.get(
        "/api/timeseries/networth", params={"scope": "net"}, headers=auth_headers
    )
    assert alloc_resp.status_code == 200
    assert net_resp.status_code == 200

    alloc_point = alloc_resp.json()[0]
    net_point = net_resp.json()[0]
    total = sum(Decimal(v) for v in alloc_point["values"].values())
    assert total == Decimal(net_point["value_eur"])


def test_allocation_timeseries_includes_non_market_valuation_modes(client, auth_headers, db_session):
    """house=ANCHORED, car=MODELED must still show up under their asset
    class — this endpoint feeds net-worth decomposition, not rebalancing,
    so it deliberately includes every valuation mode (unlike
    allocation_service.current_allocation's MARKET-only filter)."""
    from app.models import DailySnapshot

    house = _seed_instrument(db_session, "REAL_ESTATE", valuation_mode="ANCHORED")
    car = _seed_instrument(db_session, "VEHICLE", valuation_mode="MODELED")

    d = date(2024, 4, 1)
    db_session.add_all(
        [
            DailySnapshot(
                date=d, scope_type="position", scope_id=f"1:{house.id}", value_eur=Decimal("400000.00")
            ),
            DailySnapshot(
                date=d, scope_type="position", scope_id=f"1:{car.id}", value_eur=Decimal("15000.00")
            ),
        ]
    )
    db_session.commit()

    resp = client.get("/api/timeseries/allocation", headers=auth_headers)
    values = resp.json()[0]["values"]
    assert values == {"REAL_ESTATE": "400000.00", "VEHICLE": "15000.00"}


def test_allocation_timeseries_from_to_filtering(client, auth_headers, db_session):
    from app.models import DailySnapshot

    equity = _seed_instrument(db_session, "EQUITY")
    db_session.add_all(
        [
            DailySnapshot(
                date=date(2024, 1, 1), scope_type="position", scope_id=f"1:{equity.id}",
                value_eur=Decimal("10.00"),
            ),
            DailySnapshot(
                date=date(2024, 1, 15), scope_type="position", scope_id=f"1:{equity.id}",
                value_eur=Decimal("20.00"),
            ),
            DailySnapshot(
                date=date(2024, 2, 1), scope_type="position", scope_id=f"1:{equity.id}",
                value_eur=Decimal("30.00"),
            ),
        ]
    )
    db_session.commit()

    resp = client.get(
        "/api/timeseries/allocation",
        params={"from": "2024-01-10", "to": "2024-01-31"},
        headers=auth_headers,
    )
    points = resp.json()
    assert len(points) == 1
    assert points[0]["date"] == "2024-01-15"
    assert points[0]["values"] == {"EQUITY": "20.00"}


def test_allocation_timeseries_requires_auth(client):
    resp = client.get("/api/timeseries/allocation")
    assert resp.status_code in (401, 403)
