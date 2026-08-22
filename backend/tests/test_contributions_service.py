"""Invented ISINs and amounts only, per AGENTS.md."""

from datetime import date, timedelta
from decimal import Decimal


def _account(client, headers, name, type_="BROKERAGE"):
    return client.post(
        "/api/accounts",
        json={"name": name, "type": type_, "currency": "EUR"},
        headers=headers,
    ).json()["id"]


def _instrument(client, headers, isin, asset_class):
    return client.post(
        "/api/instruments",
        json={
            "name": f"Test {asset_class}", "isin": isin,
            "asset_class": asset_class, "valuation_mode": "MARKET",
            "currency": "EUR",
        },
        headers=headers,
    ).json()["id"]


def _buy(client, headers, ext, account, instrument, day, qty, price, type_="BUY"):
    return client.post(
        "/api/transactions",
        json={
            "external_id": ext, "date": day, "type": type_,
            "account_id": account, "instrument_id": instrument,
            "quantity": qty, "price": price, "currency": "EUR",
        },
        headers=headers,
    )


def test_groups_net_investment_by_asset_class(client, auth_headers, db_session):
    from app.contributions_service import compute_contributions

    account = _account(client, auth_headers, "Depot")
    equity = _instrument(client, auth_headers, "XX0000001001", "EQUITY")
    crypto = _instrument(client, auth_headers, "XX0000001002", "CRYPTO")

    _buy(client, auth_headers, "c-1", account, equity, "2025-03-01", "10", "100.00")
    _buy(client, auth_headers, "c-2", account, crypto, "2025-04-01", "1", "500.00")
    # A sale nets off against purchases in the same class: swapping one ETF
    # for another is not fresh money.
    _buy(client, auth_headers, "c-3", account, equity, "2025-05-01", "3", "110.00", "SELL")

    result = compute_contributions(db_session, date(2025, 1, 1), date(2025, 12, 31))
    assert result.by_asset_class["EQUITY"] == Decimal("670.00")  # 1000 - 330
    assert result.by_asset_class["CRYPTO"] == Decimal("500.00")
    assert result.total_invested == Decimal("1170.00")


def test_window_is_exclusive_at_the_start(client, auth_headers, db_session):
    """`start` is the *baseline* date, as it is for attribution: a purchase
    made on the opening date belongs to the previous period, or a 12-month
    window would double-count the boundary day when windows are chained."""
    from app.contributions_service import compute_contributions

    account = _account(client, auth_headers, "Depot")
    equity = _instrument(client, auth_headers, "XX0000001003", "EQUITY")
    _buy(client, auth_headers, "c-edge-1", account, equity, "2025-06-01", "1", "100.00")
    _buy(client, auth_headers, "c-edge-2", account, equity, "2025-06-02", "1", "200.00")

    result = compute_contributions(db_session, date(2025, 6, 1), date(2025, 6, 30))
    assert result.by_asset_class == {"EQUITY": Decimal("200.00")}


def test_zero_net_class_is_omitted_not_reported_as_zero(client, auth_headers, db_session):
    from app.contributions_service import compute_contributions

    account = _account(client, auth_headers, "Depot")
    equity = _instrument(client, auth_headers, "XX0000001004", "EQUITY")
    _buy(client, auth_headers, "c-z-1", account, equity, "2025-02-01", "5", "100.00")
    _buy(client, auth_headers, "c-z-2", account, equity, "2025-03-01", "5", "100.00", "SELL")

    result = compute_contributions(db_session, date(2025, 1, 1), date(2025, 12, 31))
    assert "EQUITY" not in result.by_asset_class
    assert result.total_invested == Decimal("0")


def test_debt_repaid_is_positive_when_principal_falls(client, auth_headers, db_session):
    from app.contributions_service import compute_contributions
    from app.models import DailySnapshot

    # Loan snapshots are stored negative; repayment makes them less negative.
    db_session.add(
        DailySnapshot(date=date(2025, 1, 1), scope_type="loan", scope_id="1",
                      value_eur=Decimal("-100000.00"))
    )
    db_session.add(
        DailySnapshot(date=date(2025, 12, 31), scope_type="loan", scope_id="1",
                      value_eur=Decimal("-94000.00"))
    )
    db_session.add(
        DailySnapshot(date=date(2025, 1, 1), scope_type="total", scope_id="net",
                      value_eur=Decimal("50000.00"))
    )
    db_session.add(
        DailySnapshot(date=date(2025, 12, 31), scope_type="total", scope_id="net",
                      value_eur=Decimal("72000.00"))
    )
    db_session.commit()

    result = compute_contributions(db_session, date(2025, 1, 1), date(2025, 12, 31))
    assert result.debt_repaid == Decimal("6000.00")
    assert result.net_worth_change == Decimal("22000.00")


def test_endpoint_defaults_to_trailing_twelve_months(client, auth_headers):
    response = client.get("/api/contributions", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    span = date.fromisoformat(body["end_date"]) - date.fromisoformat(body["start_date"])
    assert span == timedelta(days=365)
    # Serialized as strings, like every other money field (ADR 0001).
    assert isinstance(body["total_invested"], str)
    assert isinstance(body["debt_repaid"], str)


def test_endpoint_requires_auth(client):
    assert client.get("/api/contributions").status_code == 401


def test_end_date_without_a_snapshot_uses_the_last_one(client, auth_headers, db_session):
    """The snapshot job runs in the evening, so a window ending "today" has
    no row for its end date for most of the day. Reading that as zero made
    the whole outstanding loan look repaid and the opening net worth look
    lost — the card showed a six-figure loss every morning."""
    from datetime import date as _date

    from app.contributions_service import compute_contributions
    from app.models import DailySnapshot

    for day, loan, net in (
        (_date(2025, 1, 1), Decimal("-100000.00"), Decimal("50000.00")),
        (_date(2025, 12, 30), Decimal("-94000.00"), Decimal("72000.00")),
    ):
        db_session.add(
            DailySnapshot(date=day, scope_type="loan", scope_id="1", value_eur=loan)
        )
        db_session.add(
            DailySnapshot(date=day, scope_type="total", scope_id="net", value_eur=net)
        )
    db_session.commit()

    # 12-31 was never snapshotted; 12-30 is the last word on the matter.
    result = compute_contributions(db_session, date(2025, 1, 1), date(2025, 12, 31))
    assert result.debt_repaid == Decimal("6000.00")
    assert result.net_worth_change == Decimal("22000.00")


def test_window_starting_before_the_ledger_reads_as_zero(client, auth_headers, db_session):
    """Carry-forward must not invent a baseline: with nothing on or before
    the start date there was genuinely nothing, so the full end value is the
    change."""
    from datetime import date as _date

    from app.contributions_service import compute_contributions
    from app.models import DailySnapshot

    db_session.add(
        DailySnapshot(date=_date(2025, 6, 1), scope_type="total", scope_id="net",
                      value_eur=Decimal("8000.00"))
    )
    db_session.commit()

    result = compute_contributions(db_session, date(2025, 1, 1), date(2025, 12, 31))
    assert result.net_worth_change == Decimal("8000.00")
