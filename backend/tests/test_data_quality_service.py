"""Invented ISINs and quantities only, per AGENTS.md."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal


def test_no_issues_for_a_freshly_priced_position(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.data_quality_service import check_data_quality
    from app.models import PricePoint

    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Fresh ETF", "isin": "XX0000000900",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    today = date.today()
    db_session.add(
        PricePoint(
            instrument_id=instrument, date=today, close=Decimal("100.00"),
            currency="EUR", provider="test", quality="ok",
        )
    )
    db_session.commit()
    client.post(
        "/api/transactions",
        json={
            "external_id": "dq-buy-1", "date": str(today), "type": "BUY",
            "account_id": account, "instrument_id": instrument,
            "quantity": "1", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )

    db = SessionLocal()
    try:
        issues = check_data_quality(db, as_of=today)
    finally:
        db.close()
    assert [i for i in issues if i.instrument_id == instrument] == []


def test_stale_price_is_flagged(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.data_quality_service import check_data_quality
    from app.models import PricePoint

    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Stale ETF", "isin": "XX0000000901",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    old_date = date(2024, 1, 1)
    db_session.add(
        PricePoint(
            instrument_id=instrument, date=old_date, close=Decimal("100.00"),
            currency="EUR", provider="test", quality="ok",
        )
    )
    db_session.commit()
    client.post(
        "/api/transactions",
        json={
            "external_id": "dq-buy-2", "date": str(old_date), "type": "BUY",
            "account_id": account, "instrument_id": instrument,
            "quantity": "1", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )

    as_of = old_date + timedelta(days=30)
    db = SessionLocal()
    try:
        issues = check_data_quality(db, as_of=as_of)
    finally:
        db.close()
    matches = [i for i in issues if i.instrument_id == instrument]
    assert len(matches) == 1
    assert matches[0].kind == "stale_price"
    assert matches[0].age_days == 30


def test_missing_price_is_flagged(client, auth_headers):
    from app.database import SessionLocal
    from app.data_quality_service import check_data_quality

    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "No Price ETF", "isin": "XX0000000902",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    client.post(
        "/api/transactions",
        json={
            "external_id": "dq-buy-3", "date": "2024-01-01", "type": "BUY",
            "account_id": account, "instrument_id": instrument,
            "quantity": "1", "price": "100.00", "currency": "EUR",
        },
        headers=auth_headers,
    )

    db = SessionLocal()
    try:
        issues = check_data_quality(db)
    finally:
        db.close()
    matches = [i for i in issues if i.instrument_id == instrument]
    assert len(matches) == 1
    assert matches[0].kind == "missing_price"


def test_zero_cost_basis_position_is_flagged(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.data_quality_service import check_data_quality
    from app.models import PricePoint

    account = client.post(
        "/api/accounts",
        json={"name": "Portfolio A", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Gifted Shares", "isin": "XX0000000903",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    today = date.today()
    db_session.add(
        PricePoint(
            instrument_id=instrument, date=today, close=Decimal("50.00"),
            currency="EUR", provider="test", quality="ok",
        )
    )
    db_session.commit()
    # A gift/grant booked at zero cost — a real, if unusual, scenario.
    client.post(
        "/api/transactions",
        json={
            "external_id": "dq-buy-4", "date": str(today), "type": "BUY",
            "account_id": account, "instrument_id": instrument,
            "quantity": "5", "price": "0.00", "currency": "EUR",
        },
        headers=auth_headers,
    )

    db = SessionLocal()
    try:
        issues = check_data_quality(db, as_of=today)
    finally:
        db.close()
    kinds = {i.kind for i in issues if i.instrument_id == instrument}
    assert "no_cost_basis" in kinds


def test_stale_house_valuation_is_flagged(client, auth_headers, db_session):
    from app.database import SessionLocal
    from app.data_quality_service import check_data_quality
    from app.models import ValuationAnchor

    house_account = client.post(
        "/api/accounts",
        json={"name": "Home", "type": "REAL_ESTATE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    house = client.post(
        "/api/instruments",
        json={
            "name": "Old House", "asset_class": "REAL_ESTATE",
            "valuation_mode": "ANCHORED", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]
    anchor_date = date(2020, 1, 1)
    db_session.add(
        ValuationAnchor(
            instrument_id=house, date=anchor_date, value_eur=Decimal("300000.00"),
            method="purchase",
        )
    )
    db_session.commit()
    client.post(
        "/api/transactions",
        json={
            "external_id": "dq-house-1", "date": str(anchor_date), "type": "OPENING_BALANCE",
            "account_id": house_account, "instrument_id": house,
            "quantity": "1", "amount": "300000.00", "currency": "EUR", "provisional": False,
        },
        headers=auth_headers,
    )

    as_of = anchor_date + timedelta(days=800)  # well past the 2-year threshold
    db = SessionLocal()
    try:
        issues = check_data_quality(db, as_of=as_of)
    finally:
        db.close()
    matches = [i for i in issues if i.instrument_id == house]
    assert len(matches) == 1
    assert matches[0].kind == "stale_valuation"


def test_data_quality_endpoint_end_to_end(client, auth_headers):
    # No positions -> no per-instrument issues, but neither backup-status
    # file exists in a test environment either, so those two issues are
    # expected rather than a fully empty list.
    resp = client.get("/api/data-quality", headers=auth_headers)
    assert resp.status_code == 200
    issues = resp.json()["issues"]
    assert [i["kind"] for i in issues] == ["missing_backup", "missing_offsite_backup"]


def test_data_quality_endpoint_requires_auth(client):
    resp = client.get("/api/data-quality")
    assert resp.status_code == 401


def test_backup_issue_missing_file(monkeypatch):
    from app import data_quality_service

    monkeypatch.setattr(
        data_quality_service, "_LAST_SUCCESS_FILE", data_quality_service.Path("/nope/does-not-exist")
    )
    issue = data_quality_service._backup_issue(datetime.now(timezone.utc))
    assert issue is not None
    assert issue.kind == "missing_backup"


def test_backup_issue_fresh_backup_is_clean(tmp_path, monkeypatch):
    from app import data_quality_service

    marker = tmp_path / "last_success"
    now = datetime.now(timezone.utc)
    marker.write_text((now - timedelta(hours=1)).isoformat())
    monkeypatch.setattr(data_quality_service, "_LAST_SUCCESS_FILE", marker)

    assert data_quality_service._backup_issue(now) is None


def test_backup_issue_stale_backup_is_flagged(tmp_path, monkeypatch):
    from app import data_quality_service

    marker = tmp_path / "last_success"
    now = datetime.now(timezone.utc)
    marker.write_text((now - timedelta(hours=72)).isoformat())
    monkeypatch.setattr(data_quality_service, "_LAST_SUCCESS_FILE", marker)

    issue = data_quality_service._backup_issue(now)
    assert issue is not None
    assert issue.kind == "stale_backup"
    assert issue.age_days == 3


def test_offsite_backup_issue_missing_file(monkeypatch):
    from app import data_quality_service

    monkeypatch.setattr(
        data_quality_service, "_LAST_OFFSITE_FILE", data_quality_service.Path("/nope/does-not-exist")
    )
    issue = data_quality_service._offsite_backup_issue(datetime.now(timezone.utc))
    assert issue is not None
    assert issue.kind == "missing_offsite_backup"


def test_offsite_backup_issue_fresh_is_clean(tmp_path, monkeypatch):
    from app import data_quality_service

    marker = tmp_path / "last_offsite_success"
    now = datetime.now(timezone.utc)
    marker.write_text((now - timedelta(hours=1)).isoformat())
    monkeypatch.setattr(data_quality_service, "_LAST_OFFSITE_FILE", marker)

    assert data_quality_service._offsite_backup_issue(now) is None


def test_offsite_backup_tolerates_a_night_the_local_backup_would_not(tmp_path, monkeypatch):
    # The whole point of the looser threshold (ADR 0015): a NAS that was
    # asleep or rebooting for a night sits in the window that already
    # counts as stale for the local backup, and must not be flagged.
    from app import data_quality_service

    marker = tmp_path / "last_offsite_success"
    now = datetime.now(timezone.utc)
    marker.write_text((now - timedelta(hours=60)).isoformat())
    monkeypatch.setattr(data_quality_service, "_LAST_OFFSITE_FILE", marker)

    assert 60 > data_quality_service.STALE_BACKUP_HOURS
    assert data_quality_service._offsite_backup_issue(now) is None


def test_offsite_backup_issue_stale_is_flagged(tmp_path, monkeypatch):
    from app import data_quality_service

    marker = tmp_path / "last_offsite_success"
    now = datetime.now(timezone.utc)
    marker.write_text((now - timedelta(hours=96)).isoformat())
    monkeypatch.setattr(data_quality_service, "_LAST_OFFSITE_FILE", marker)

    issue = data_quality_service._offsite_backup_issue(now)
    assert issue is not None
    assert issue.kind == "stale_offsite_backup"
    assert issue.age_days == 4


def test_unparseable_marker_reads_as_never_succeeded(tmp_path, monkeypatch):
    # The panel that reports a broken backup must not itself 500 on a
    # truncated marker file — that would hide the very thing it exists
    # to show.
    from app import data_quality_service

    marker = tmp_path / "last_success"
    marker.write_text("not-a-timestamp")
    monkeypatch.setattr(data_quality_service, "_LAST_SUCCESS_FILE", marker)

    issue = data_quality_service._backup_issue(datetime.now(timezone.utc))
    assert issue is not None
    assert issue.kind == "missing_backup"


def test_stale_offsite_does_not_affect_local_backup_and_vice_versa(tmp_path, monkeypatch):
    # Two independent signals (ADR 0015): a dead NAS must never make the
    # dashboard claim the local backup failed, and a healthy local backup
    # must never hide a dead NAS.
    from app import data_quality_service

    now = datetime.now(timezone.utc)
    local = tmp_path / "last_success"
    local.write_text((now - timedelta(hours=1)).isoformat())
    offsite = tmp_path / "last_offsite_success"
    offsite.write_text((now - timedelta(days=30)).isoformat())
    monkeypatch.setattr(data_quality_service, "_LAST_SUCCESS_FILE", local)
    monkeypatch.setattr(data_quality_service, "_LAST_OFFSITE_FILE", offsite)

    assert data_quality_service._backup_issue(now) is None
    assert data_quality_service._offsite_backup_issue(now).kind == "stale_offsite_backup"

    # And the mirror image.
    local.write_text((now - timedelta(days=30)).isoformat())
    offsite.write_text((now - timedelta(hours=1)).isoformat())

    assert data_quality_service._backup_issue(now).kind == "stale_backup"
    assert data_quality_service._offsite_backup_issue(now) is None


def _cash_account_with_statement(client, auth_headers, name, ext_id, when):
    account = client.post(
        "/api/accounts",
        json={"name": name, "type": "CASH", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    client.post(
        "/api/transactions",
        json={
            "external_id": ext_id, "date": str(when), "type": "BALANCE_STATEMENT",
            "account_id": account, "amount": "1000.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    return account


def test_stale_cash_statement_is_flagged(client, auth_headers):
    """The snapshot engine carries the last balance forward forever, so
    ageing is the only thing that keeps a carried figure honest."""
    from app.data_quality_service import STALE_CASH_STATEMENT_DAYS, check_data_quality
    from app.database import SessionLocal

    today = date.today()
    old = today - timedelta(days=STALE_CASH_STATEMENT_DAYS + 5)
    account = _cash_account_with_statement(client, auth_headers, "Altes Giro", "dq-cash-old", old)

    db = SessionLocal()
    try:
        issues = check_data_quality(db, as_of=today)
    finally:
        db.close()
    flagged = [i for i in issues if i.kind == "stale_cash_statement" and i.account_id == account]
    assert len(flagged) == 1
    assert flagged[0].age_days == STALE_CASH_STATEMENT_DAYS + 5


def test_recent_cash_statement_is_not_flagged(client, auth_headers):
    from app.data_quality_service import check_data_quality
    from app.database import SessionLocal

    today = date.today()
    account = _cash_account_with_statement(
        client, auth_headers, "Frisches Giro", "dq-cash-new", today - timedelta(days=3)
    )

    db = SessionLocal()
    try:
        issues = check_data_quality(db, as_of=today)
    finally:
        db.close()
    assert [i for i in issues if i.kind == "stale_cash_statement" and i.account_id == account] == []


def test_cash_account_without_any_statement_is_not_flagged(client, auth_headers):
    """An account that was never given a balance holds nothing and is
    reported as nothing — there is no stale figure to warn about."""
    from app.data_quality_service import check_data_quality
    from app.database import SessionLocal

    account = client.post(
        "/api/accounts",
        json={"name": "Leeres Konto", "type": "CASH", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]

    db = SessionLocal()
    try:
        issues = check_data_quality(db, as_of=date.today())
    finally:
        db.close()
    assert [i for i in issues if i.account_id == account] == []
