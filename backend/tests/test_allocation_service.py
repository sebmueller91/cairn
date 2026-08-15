from decimal import Decimal

from app.allocation_service import (
    DriftRow,
    compute_drift,
    full_rebalance_proposal,
    purchases_only_proposal,
)


def _setup_positions(client, auth_headers, db_session):
    from datetime import date
    from app.models import PricePoint

    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    equity = client.post(
        "/api/instruments",
        json={
            "name": "Equity ETF", "isin": "XX0000000800",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    bond = client.post(
        "/api/instruments",
        json={
            "name": "Bond ETF", "isin": "XX0000000801",
            "asset_class": "BOND", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    for iid, price, ext in [(equity, "100.00", "alloc-eq"), (bond, "100.00", "alloc-bond")]:
        db_session.add(
            PricePoint(
                instrument_id=iid, date=date(2024, 1, 1), close=Decimal(price),
                currency="EUR", provider="test", quality="ok",
            )
        )
    db_session.commit()
    client.post(
        "/api/transactions",
        json={
            "external_id": "alloc-buy-eq", "date": "2024-01-01", "type": "BUY",
            "account_id": account, "instrument_id": equity,
            "quantity": "7", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    client.post(
        "/api/transactions",
        json={
            "external_id": "alloc-buy-bond", "date": "2024-01-01", "type": "BUY",
            "account_id": account, "instrument_id": bond,
            "quantity": "3", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    client.post("/api/admin/rebuild-snapshots", headers=auth_headers)


def test_targets_endpoint_round_trip(client, auth_headers):
    resp = client.put(
        "/api/allocation/targets",
        json={"targets": {"EQUITY": "60", "BOND": "40"}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"EQUITY": "60", "BOND": "40"}

    resp = client.get("/api/allocation/targets", headers=auth_headers)
    assert resp.json() == {"EQUITY": "60", "BOND": "40"}


def test_targets_endpoint_rejects_non_100_sum(client, auth_headers):
    resp = client.put(
        "/api/allocation/targets",
        json={"targets": {"EQUITY": "60", "BOND": "30"}},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "targets_must_sum_to_100"


def test_targets_endpoint_requires_write_scope(client, readonly_headers):
    resp = client.put(
        "/api/allocation/targets",
        json={"targets": {"EQUITY": "100"}},
        headers=readonly_headers,
    )
    assert resp.status_code == 403


def test_allocation_endpoint_end_to_end(client, auth_headers, db_session):
    _setup_positions(client, auth_headers, db_session)
    client.put(
        "/api/allocation/targets",
        json={"targets": {"EQUITY": "60", "BOND": "40"}},
        headers=auth_headers,
    )

    resp = client.get("/api/allocation", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    by_class = {row["asset_class"]: row for row in body["drift"]}
    # 700 equity / 300 bond, current 70/30 vs target 60/40
    assert by_class["EQUITY"]["current_pct"] == "70.0"
    assert by_class["BOND"]["drift_pp"] == "-10.0"
    rebalance = {p["asset_class"]: p["amount_eur"] for p in body["rebalance_full"]}
    assert rebalance == {"EQUITY": "-100.000", "BOND": "100.000"}
    assert body["rebalance_purchases_only"] is None


def test_allocation_endpoint_with_contribution(client, auth_headers, db_session):
    _setup_positions(client, auth_headers, db_session)
    client.put(
        "/api/allocation/targets",
        json={"targets": {"EQUITY": "60", "BOND": "40"}},
        headers=auth_headers,
    )
    resp = client.get("/api/allocation", params={"contribution": "50"}, headers=auth_headers)
    body = resp.json()
    purchases = {p["asset_class"]: p["amount_eur"] for p in body["rebalance_purchases_only"]}
    assert purchases == {"BOND": "50"}


def test_compute_drift_hand_derived():
    current = {"EQUITY": Decimal(700), "BOND": Decimal(300)}
    targets = {"EQUITY": Decimal(60), "BOND": Decimal(40)}
    rows = {r.asset_class: r for r in compute_drift(current, targets)}

    assert rows["EQUITY"].current_pct == Decimal(70)
    assert rows["EQUITY"].drift_pp == Decimal(10)
    assert rows["EQUITY"].drift_value == Decimal(100)  # 700 - 600 target

    assert rows["BOND"].current_pct == Decimal(30)
    assert rows["BOND"].drift_pp == Decimal(-10)
    assert rows["BOND"].drift_value == Decimal(-100)  # 300 - 400 target


def test_compute_drift_includes_a_class_with_no_current_holding():
    current = {"EQUITY": Decimal(1000)}
    targets = {"EQUITY": Decimal(80), "COMMODITY": Decimal(20)}
    rows = {r.asset_class: r for r in compute_drift(current, targets)}
    assert rows["COMMODITY"].current_value == Decimal(0)
    assert rows["COMMODITY"].drift_value == Decimal(-200)  # 0 - 20% of 1000


def test_full_rebalance_proposal_buys_underweight_sells_overweight():
    drift = compute_drift(
        {"EQUITY": Decimal(700), "BOND": Decimal(300)},
        {"EQUITY": Decimal(60), "BOND": Decimal(40)},
    )
    proposals = {p.asset_class: p.amount for p in full_rebalance_proposal(drift)}
    assert proposals == {"EQUITY": Decimal(-100), "BOND": Decimal(100)}


def test_purchases_only_partial_contribution_goes_entirely_to_the_gap():
    drift = compute_drift(
        {"EQUITY": Decimal(700), "BOND": Decimal(300)},
        {"EQUITY": Decimal(60), "BOND": Decimal(40)},
    )
    proposals = purchases_only_proposal(drift, Decimal(50))
    assert len(proposals) == 1
    assert proposals[0].asset_class == "BOND"
    assert proposals[0].amount == Decimal(50)


def test_purchases_only_overfunded_contribution_tops_up_then_spreads_remainder():
    drift = compute_drift(
        {"EQUITY": Decimal(700), "BOND": Decimal(300)},
        {"EQUITY": Decimal(60), "BOND": Decimal(40)},
    )
    # Shortfall is exactly 100 (BOND). Contribute 150 -> BOND closes to
    # 100, remaining 50 splits 60/40 by target weight: EQUITY +30, BOND +20.
    proposals = {p.asset_class: p.amount for p in purchases_only_proposal(drift, Decimal(150))}
    assert proposals == {"EQUITY": Decimal(30), "BOND": Decimal(120)}


def test_purchases_only_never_proposes_a_sale():
    drift = compute_drift(
        {"EQUITY": Decimal(700), "BOND": Decimal(300)},
        {"EQUITY": Decimal(60), "BOND": Decimal(40)},
    )
    for p in purchases_only_proposal(drift, Decimal(1000)):
        assert p.amount >= 0


def test_purchases_only_zero_contribution_is_a_no_op():
    drift = [DriftRow("EQUITY", Decimal(0), Decimal(0), Decimal(100), Decimal(-100), Decimal(-100))]
    assert purchases_only_proposal(drift, Decimal(0)) == []


def test_purchases_only_already_on_target_spreads_by_target_weight():
    drift = compute_drift(
        {"EQUITY": Decimal(600), "BOND": Decimal(400)},
        {"EQUITY": Decimal(60), "BOND": Decimal(40)},
    )
    proposals = {p.asset_class: p.amount for p in purchases_only_proposal(drift, Decimal(100))}
    assert proposals == {"EQUITY": Decimal(60), "BOND": Decimal(40)}
