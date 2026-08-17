"""Regions compared against the world market, and instruments that have
no geography at all.

Gold and bitcoin used to land in a catch-all bucket that became the
third-largest slice of the region chart, shrinking every real region's
share. NOT_APPLICABLE takes them out of that dimension while leaving
them in sectors, where "Precious Metals" and "Crypto" are meaningful.
"""

from datetime import date
from decimal import Decimal

from app.look_through_service import NOT_APPLICABLE, compute_look_through
from app.models import (
    Account,
    AccountType,
    AssetClass,
    ImportBatch,
    Instrument,
    PricePoint,
    TransactionType,
    Txn,
    TxnSource,
    ValuationMode,
)

TODAY = date(2026, 8, 16)


def _hold(db, instrument, quantity, price, account):
    batch = ImportBatch(label="t", source=TxnSource.AGENT)
    db.add(batch)
    db.flush()
    db.add(Txn(
        external_id=f"open-{instrument.id}", payload_hash="n/a", import_batch_id=batch.id,
        date=date(2025, 1, 1), type=TransactionType.OPENING_BALANCE,
        account_id=account.id, instrument_id=instrument.id, quantity=Decimal(quantity),
        currency="EUR", fees=Decimal(0), tax=Decimal(0),
        amount_eur=Decimal(quantity) * Decimal(price), source=TxnSource.AGENT,
    ))
    db.add(PricePoint(
        instrument_id=instrument.id, date=date(2025, 1, 1), close=Decimal(price),
        currency="EUR", provider="test",
    ))
    db.commit()


def _instrument(db, name, region, sector, asset_class=AssetClass.EQUITY):
    inst = Instrument(
        name=name, asset_class=asset_class, valuation_mode=ValuationMode.MARKET,
        currency="EUR", region=region, sector=sector,
    )
    db.add(inst)
    db.flush()
    return inst


def _setup(db):
    account = Account(name="depot", type=AccountType.BROKERAGE, currency="EUR")
    db.add(account)
    db.flush()
    share = _instrument(db, "US share", "North America", "Financials")
    gold = _instrument(db, "Gold", NOT_APPLICABLE, "Precious Metals", AssetClass.COMMODITY)
    _hold(db, share, "10", "100", account)   # 1000 EUR
    _hold(db, gold, "10", "50", account)     # 500 EUR
    return account


def test_not_applicable_is_excluded_from_its_dimension(db_session):
    _setup(db_session)
    rows = compute_look_through(db_session, "region", as_of=TODAY)
    assert [(r.category, r.value_eur) for r in rows] == [
        ("North America", Decimal(1000))
    ]
    assert NOT_APPLICABLE not in [r.category for r in rows]


def test_the_same_instrument_still_counts_in_the_other_dimension(db_session):
    _setup(db_session)
    rows = compute_look_through(db_session, "sector", as_of=TODAY)
    by_category = {r.category: r.value_eur for r in rows}
    assert by_category["Precious Metals"] == Decimal(500)
    assert by_category["Financials"] == Decimal(1000)


def test_an_empty_field_still_reads_as_unknown(db_session):
    """Absent is not the same as inapplicable — a blank field means
    nobody has entered it yet and must stay visible."""
    account = Account(name="d", type=AccountType.BROKERAGE, currency="EUR")
    db_session.add(account)
    db_session.flush()
    thing = _instrument(db_session, "mystery", None, None)
    _hold(db_session, thing, "1", "100", account)

    rows = compute_look_through(db_session, "region", as_of=TODAY)
    assert [r.category for r in rows] == ["Unknown"]


def test_benchmark_round_trips(client, auth_headers):
    response = client.put("/api/look-through/benchmark", json={
        "dimension": "region", "label": "MSCI ACWI",
        "breakdown": {"North America": "66", "Europe": "34"},
    }, headers=auth_headers)
    assert response.status_code == 200

    read = client.get("/api/look-through/benchmark?dimension=region",
                      headers=auth_headers).json()
    assert read["label"] == "MSCI ACWI"
    assert read["breakdown"] == {"North America": "66", "Europe": "34"}


def test_benchmark_must_sum_to_about_100(client, auth_headers):
    response = client.put("/api/look-through/benchmark", json={
        "dimension": "region", "label": "broken",
        "breakdown": {"North America": "66", "Europe": "10"},
    }, headers=auth_headers)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "benchmark_must_sum_to_100"


def test_look_through_carries_benchmark_weights(client, auth_headers, db_session):
    _setup(db_session)
    client.put("/api/look-through/benchmark", json={
        "dimension": "region", "label": "MSCI ACWI",
        "breakdown": {"North America": "66", "Europe": "34"},
    }, headers=auth_headers)

    body = client.get("/api/look-through?dimension=region", headers=auth_headers).json()

    assert body["benchmark_label"] == "MSCI ACWI"
    rows = {r["category"]: r for r in body["rows"]}
    assert rows["North America"]["benchmark_pct"] == "66"
    # Holding nothing where the world holds 34% is the whole point of the
    # comparison, so the row has to exist rather than being dropped.
    assert rows["Europe"]["value_eur"] == "0"
    assert rows["Europe"]["benchmark_pct"] == "34"


def test_no_benchmark_configured_leaves_rows_untouched(client, auth_headers, db_session):
    _setup(db_session)
    body = client.get("/api/look-through?dimension=sector", headers=auth_headers).json()
    assert body["benchmark_label"] is None
    assert all(r["benchmark_pct"] is None for r in body["rows"])
