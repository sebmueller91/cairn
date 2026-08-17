"""Look-through breakdowns are hand-entered, so their age is the only
signal that they've drifted. These cover the data quality checks that
surface it.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from app.data_quality_service import STALE_COMPOSITION_DAYS, check_data_quality
from app.models import (
    Account,
    AccountType,
    AssetClass,
    EtfComposition,
    ImportBatch,
    Instrument,
    TransactionType,
    Txn,
    TxnSource,
    ValuationMode,
)

TODAY = date(2026, 8, 16)


def _held_instrument(db):
    account = Account(name="depot", type=AccountType.BROKERAGE, currency="EUR")
    instrument = Instrument(
        name="Some World ETF", asset_class=AssetClass.EQUITY,
        valuation_mode=ValuationMode.MARKET, currency="EUR",
    )
    batch = ImportBatch(label="t", source=TxnSource.AGENT)
    db.add_all([account, instrument, batch])
    db.flush()
    db.add(Txn(
        external_id="open-1", payload_hash="n/a", import_batch_id=batch.id,
        date=date(2025, 1, 1), type=TransactionType.OPENING_BALANCE,
        account_id=account.id, instrument_id=instrument.id,
        quantity=Decimal(10), currency="EUR", fees=Decimal(0), tax=Decimal(0),
        amount_eur=Decimal(1000), source=TxnSource.AGENT,
    ))
    db.commit()
    return instrument


def _kinds(db, kind):
    return [i for i in check_data_quality(db, as_of=TODAY) if i.kind == kind]


def _composition(db, instrument_id, updated_at, dimension="region"):
    db.add(EtfComposition(
        instrument_id=instrument_id, dimension=dimension, category="North America",
        weight_pct=Decimal(100), updated_at=updated_at,
    ))
    db.commit()


def test_fresh_breakdown_is_not_flagged(db_session):
    instrument = _held_instrument(db_session)
    _composition(db_session, instrument.id, datetime(2026, 6, 1))
    assert _kinds(db_session, "stale_composition") == []
    assert _kinds(db_session, "composition_age_unknown") == []


def test_breakdown_older_than_a_year_is_flagged(db_session):
    instrument = _held_instrument(db_session)
    old = datetime.combine(TODAY, datetime.min.time()) - timedelta(
        days=STALE_COMPOSITION_DAYS + 30
    )
    _composition(db_session, instrument.id, old)

    issues = _kinds(db_session, "stale_composition")
    assert len(issues) == 1
    assert issues[0].instrument_id == instrument.id
    assert issues[0].age_days == STALE_COMPOSITION_DAYS + 30
    assert "region" in issues[0].detail


def test_breakdown_without_a_date_reports_unknown_age(db_session):
    """Rows predating the column keep NULL — reported as unknown rather
    than silently treated as fresh."""
    instrument = _held_instrument(db_session)
    _composition(db_session, instrument.id, None)

    issues = _kinds(db_session, "composition_age_unknown")
    assert len(issues) == 1
    assert issues[0].age_days is None


def test_oldest_row_in_a_pair_sets_the_age(db_session):
    """A partially hand-edited breakdown must not look fresh because one
    of its rows was touched recently."""
    instrument = _held_instrument(db_session)
    old = datetime.combine(TODAY, datetime.min.time()) - timedelta(
        days=STALE_COMPOSITION_DAYS + 10
    )
    _composition(db_session, instrument.id, old)
    db_session.add(EtfComposition(
        instrument_id=instrument.id, dimension="region", category="Europe",
        weight_pct=Decimal(0), updated_at=datetime(2026, 8, 1),
    ))
    db_session.commit()

    assert len(_kinds(db_session, "stale_composition")) == 1


def test_instrument_without_any_breakdown_is_not_flagged(db_session):
    """A directly-held share has no breakdown by design; absence is not
    staleness, and a genuinely missing one shows as Unknown in the
    look-through itself."""
    _held_instrument(db_session)
    assert _kinds(db_session, "stale_composition") == []
    assert _kinds(db_session, "composition_age_unknown") == []


def test_breakdown_on_an_unheld_instrument_is_ignored(db_session):
    """Sold out: the breakdown no longer affects any chart, so nagging
    about its age would be noise."""
    instrument = Instrument(
        name="sold", asset_class=AssetClass.EQUITY,
        valuation_mode=ValuationMode.MARKET, currency="EUR",
    )
    db_session.add(instrument)
    db_session.flush()
    _composition(db_session, instrument.id, None)
    assert _kinds(db_session, "composition_age_unknown") == []


def test_put_stamps_the_entry_date(client, auth_headers):
    created = client.post("/api/instruments", json={
        "name": "ETF", "asset_class": "EQUITY", "valuation_mode": "MARKET",
        "currency": "EUR",
    }, headers=auth_headers).json()

    response = client.put(
        f"/api/instruments/{created['id']}/composition",
        json={"dimension": "region", "breakdown": {"Europe": "100"}},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()[0]["updated_at"] is not None
