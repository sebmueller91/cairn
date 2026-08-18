"""Invented ISINs and weights only, per AGENTS.md."""

from datetime import date
from decimal import Decimal


def _setup(client, headers, db_session, tags, region, quantity="10", price="100.00", isin="XX0000002001"):
    from app.models import PricePoint

    account = client.post(
        "/api/accounts",
        json={"name": "Depot", "type": "BROKERAGE", "currency": "EUR"},
        headers=headers,
    ).json()["id"]
    instrument = client.post(
        "/api/instruments",
        json={
            "name": f"Fund {isin}", "isin": isin, "asset_class": "EQUITY",
            "valuation_mode": "MARKET", "currency": "EUR", "tags": tags,
        },
        headers=headers,
    ).json()["id"]
    db_session.add(
        PricePoint(instrument_id=instrument, date=date.today(), close=Decimal(price),
                   currency="EUR", provider="test", quality="ok")
    )
    db_session.commit()
    client.post(
        "/api/transactions",
        json={
            "external_id": f"split-{isin}", "date": str(date.today()), "type": "BUY",
            "account_id": account, "instrument_id": instrument,
            "quantity": quantity, "price": price, "currency": "EUR",
        },
        headers=headers,
    )
    if region:
        client.put(
            f"/api/instruments/{instrument}/composition",
            json={"dimension": "region", "breakdown": region},
            headers=headers,
        )
    return instrument


def test_weights_each_fund_by_its_own_emerging_share(client, auth_headers, db_session):
    """The point of the whole thing: an all-world fund is not one bucket or
    the other, it is both, and its emerging slice counts as emerging."""
    from app.look_through_service import compute_etf_split

    _setup(client, auth_headers, db_session, ["etf"],
           {"North America": "89", "Emerging Asia": "11"}, isin="XX0000002001")

    split = compute_etf_split(db_session)
    assert split.total_eur == Decimal("1000.00")
    assert split.emerging_eur == Decimal("110.00")
    assert split.emerging_pct == Decimal("11")


def test_ignores_holdings_that_are_not_funds(client, auth_headers, db_session):
    from app.look_through_service import compute_etf_split

    _setup(client, auth_headers, db_session, ["etf"],
           {"Emerging Asia": "100"}, isin="XX0000002002")
    _setup(client, auth_headers, db_session, ["direct"],
           {}, isin="XX0000002003")

    split = compute_etf_split(db_session)
    assert split.total_eur == Decimal("1000.00")
    assert [r.name for r in split.rows] == ["Fund XX0000002002"]


def test_fund_without_a_breakdown_counts_as_developed(client, auth_headers, db_session):
    """Dropping it would shrink the denominator and quietly inflate the
    emerging share — a missing breakdown must not move the number it is
    missing from. data_quality flags the gap separately."""
    from app.look_through_service import compute_etf_split

    _setup(client, auth_headers, db_session, ["etf"], {}, isin="XX0000002004")

    split = compute_etf_split(db_session)
    assert split.developed_eur == Decimal("1000.00")
    assert split.emerging_eur == Decimal("0")


def test_target_and_drift(client, auth_headers, db_session):
    from app.look_through_service import compute_etf_split, set_etf_split_target

    _setup(client, auth_headers, db_session, ["etf"],
           {"North America": "70", "Emerging Asia": "30"}, isin="XX0000002005")
    set_etf_split_target(db_session, Decimal("25"))
    db_session.commit()

    split = compute_etf_split(db_session)
    assert split.target_emerging_pct == Decimal("25")
    assert split.drift_pp == Decimal("5")


def test_no_target_means_no_drift(client, auth_headers, db_session):
    from app.look_through_service import compute_etf_split

    _setup(client, auth_headers, db_session, ["etf"],
           {"Emerging Asia": "100"}, isin="XX0000002006")

    split = compute_etf_split(db_session)
    assert split.target_emerging_pct is None
    assert split.drift_pp is None


def test_share_of_nothing_is_none_not_zero(client, auth_headers, db_session):
    from app.look_through_service import compute_etf_split

    split = compute_etf_split(db_session)
    assert split.total_eur == Decimal(0)
    assert split.emerging_pct is None


def test_target_endpoint_rejects_out_of_range(client, auth_headers):
    response = client.put(
        "/api/look-through/etf-split/target",
        json={"emerging_pct": "140"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "etf_split_target_out_of_range"


def test_target_can_be_cleared(client, auth_headers, db_session):
    from app.look_through_service import get_etf_split_target, set_etf_split_target

    set_etf_split_target(db_session, Decimal("30"))
    db_session.commit()
    assert get_etf_split_target(db_session) == Decimal("30")

    client.put("/api/look-through/etf-split/target", json={"emerging_pct": None},
               headers=auth_headers)
    db_session.expire_all()
    assert get_etf_split_target(db_session) is None


def test_endpoint_requires_auth(client):
    assert client.get("/api/look-through/etf-split").status_code == 401


def test_same_fund_in_two_depots_is_one_row(client, auth_headers, db_session):
    """compute_positions keys by (account, instrument), but two depots
    holding the same fund is one holding to the reader — listing it twice
    reads as two different funds with identical names."""
    from datetime import date
    from decimal import Decimal

    from app.look_through_service import compute_etf_split
    from app.models import PricePoint

    instrument = client.post(
        "/api/instruments",
        json={
            "name": "World Fund", "isin": "XX0000002007", "asset_class": "EQUITY",
            "valuation_mode": "MARKET", "currency": "EUR", "tags": ["etf"],
        },
        headers=auth_headers,
    ).json()["id"]
    db_session.add(
        PricePoint(instrument_id=instrument, date=date.today(), close=Decimal("100.00"),
                   currency="EUR", provider="test", quality="ok")
    )
    db_session.commit()
    client.put(
        f"/api/instruments/{instrument}/composition",
        json={"dimension": "region", "breakdown": {"North America": "80", "Emerging Asia": "20"}},
        headers=auth_headers,
    )
    for n, name in enumerate(["Depot A", "Depot B"]):
        account = client.post(
            "/api/accounts", json={"name": name, "type": "BROKERAGE", "currency": "EUR"},
            headers=auth_headers,
        ).json()["id"]
        client.post(
            "/api/transactions",
            json={
                "external_id": f"two-depots-{n}", "date": str(date.today()), "type": "BUY",
                "account_id": account, "instrument_id": instrument,
                "quantity": "10", "price": "100.00", "currency": "EUR",
            },
            headers=auth_headers,
        )

    split = compute_etf_split(db_session)
    assert len(split.rows) == 1
    assert split.rows[0].value_eur == Decimal("2000.00")
    assert split.rows[0].emerging_pct == Decimal("20")
