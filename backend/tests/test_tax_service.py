"""Invented ISINs, quantities, and amounts only, per AGENTS.md.

Every expected figure below is derived by hand in a comment next to the
assertion. That is the point of the file: the §20/§23 split, the
speculation period and the Freigrenze cliff are all rules where a
plausible-looking wrong number is the failure mode.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.database import SessionLocal


def _account(client, auth_headers, name, type_="BROKERAGE"):
    return client.post(
        "/api/accounts",
        json={"name": name, "type": type_, "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]


def _instrument(client, auth_headers, name, isin, asset_class="EQUITY", **extra):
    return client.post(
        "/api/instruments",
        json={
            "name": name, "isin": isin, "asset_class": asset_class,
            "valuation_mode": "MARKET", "currency": "EUR", **extra,
        },
        headers=auth_headers,
    ).json()["id"]


def _price(db_session, instrument, on, close):
    from app.models import PricePoint

    db_session.add(
        PricePoint(
            instrument_id=instrument, date=on, close=Decimal(close),
            currency="EUR", provider="test", quality="ok",
        )
    )
    db_session.commit()


def _txn(client, auth_headers, external_id, **body):
    resp = client.post(
        "/api/transactions",
        json={"external_id": external_id, "currency": "EUR", **body},
        headers=auth_headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp


def _setup(client, auth_headers, db_session):
    """An equity position: buy 10 @ 100, sell 5 @ 120 mid-year."""
    account = _account(client, auth_headers, "Portfolio A")
    instrument = _instrument(client, auth_headers, "Test ETF", "XX0000001100")
    _price(db_session, instrument, date(2024, 1, 1), "100.00")
    _txn(
        client, auth_headers, "tax-buy-1", date="2024-01-01", type="BUY",
        account_id=account, instrument_id=instrument, quantity="10", price="100.00",
    )
    _txn(
        client, auth_headers, "tax-sell-1", date="2024-06-01", type="SELL",
        account_id=account, instrument_id=instrument, quantity="5", price="120.00",
    )
    return account, instrument


def _session(fn):
    db = SessionLocal()
    try:
        return fn(db)
    finally:
        db.close()


# --------------------------------------------------------------------
# Holding period arithmetic
# --------------------------------------------------------------------


def test_holding_period_needs_to_be_exceeded_not_merely_reached():
    """§23 requires the period between acquisition and sale to *exceed*
    one year, so the anniversary itself is still inside it."""
    from app.ledger import holding_period_elapsed

    assert not holding_period_elapsed(date(2024, 3, 10), date(2025, 3, 10), 1)
    assert holding_period_elapsed(date(2024, 3, 10), date(2025, 3, 11), 1)


def test_holding_period_counts_calendar_years_not_365_days():
    """A leap year contains 366 days. Counting days would call a sale on
    2025-02-28 tax-free when the statute does not."""
    from app.ledger import holding_period_elapsed

    # 2024-02-29 -> 2025-02-28 is 365 days but not a full calendar year.
    assert not holding_period_elapsed(date(2024, 2, 29), date(2025, 2, 28), 1)
    assert holding_period_elapsed(date(2024, 2, 29), date(2025, 3, 1), 1)


def test_add_years_clamps_leap_day_into_a_non_leap_year():
    from app.ledger import add_years

    assert add_years(date(2024, 2, 29), 1) == date(2025, 2, 28)
    assert add_years(date(2024, 2, 29), 4) == date(2028, 2, 29)


# --------------------------------------------------------------------
# Regime classification
# --------------------------------------------------------------------


def test_asset_class_picks_the_default_regime(client, auth_headers, db_session):
    from app.models import Instrument, TaxTreatment
    from app.tax_service import tax_treatment_of

    _instrument(client, auth_headers, "Equity ETF", "XX0000002100", "EQUITY")
    _instrument(client, auth_headers, "Coin", "XX0000002200", "CRYPTO")
    _instrument(client, auth_headers, "Bar", "XX0000002300", "COMMODITY")

    def check(db):
        by_name = {i.name: i for i in db.query(Instrument).all()}
        assert tax_treatment_of(by_name["Equity ETF"]) is TaxTreatment.CAPITAL_GAINS
        assert tax_treatment_of(by_name["Coin"]) is TaxTreatment.PRIVATE_SALE
        assert tax_treatment_of(by_name["Bar"]) is TaxTreatment.PRIVATE_SALE

    _session(check)


def test_explicit_treatment_overrides_the_asset_class_default(client, auth_headers):
    """A swap-based commodity ETC is §20 despite tracking metal — the
    case asset_class provably cannot decide on its own."""
    from app.models import Instrument, TaxTreatment
    from app.tax_service import tax_treatment_of

    iid = _instrument(
        client, auth_headers, "Synthetic Metal ETC", "XX0000002400", "COMMODITY",
        tax_treatment="CAPITAL_GAINS",
    )

    def check(db):
        assert tax_treatment_of(db.get(Instrument, iid)) is TaxTreatment.CAPITAL_GAINS

    _session(check)


def test_property_gets_the_ten_year_speculation_period(client, auth_headers):
    from app.models import Instrument
    from app.tax_service import speculation_period_years

    iid = _instrument(
        client, auth_headers, "Plot", "XX0000002500", "REAL_ESTATE",
    )

    def check(db):
        assert speculation_period_years(db.get(Instrument, iid)) == 10

    _session(check)


# --------------------------------------------------------------------
# Realized gains, split by regime
# --------------------------------------------------------------------


def test_realized_gains_fifo_hand_derived(client, auth_headers, db_session):
    from app.tax_service import realized_sales

    _setup(client, auth_headers, db_session)
    sales = _session(realized_sales)

    # Sold 5 @ 120 = 600 proceeds; cost of those 5 units @ 100 = 500 -> gain 100.
    assert len(sales) == 1
    assert sales[0].date == date(2024, 6, 1)
    assert sales[0].gain_eur == Decimal("100.00")


def test_crypto_held_over_a_year_is_realized_tax_free(client, auth_headers, db_session):
    from app.tax_service import realized_gains_by_regime

    account = _account(client, auth_headers, "Wallet", "CRYPTO_WALLET")
    coin = _instrument(client, auth_headers, "Coin", "XX0000003100", "CRYPTO")
    _txn(
        client, auth_headers, "c-buy", date="2023-01-10", type="BUY",
        account_id=account, instrument_id=coin, quantity="2", price="1000.00",
    )
    # Sold well over a year later: §23 exempt, whatever the gain.
    _txn(
        client, auth_headers, "c-sell", date="2024-06-10", type="SELL",
        account_id=account, instrument_id=coin, quantity="2", price="3000.00",
    )

    gains = _session(lambda db: realized_gains_by_regime(db, 2024))

    # Proceeds 6000 - cost 2000 = 4000, all of it outside the one-year period.
    assert gains.private_sale_exempt_eur == Decimal("4000.00")
    assert gains.private_sale_taxable_eur == Decimal(0)
    # And crucially it must NOT land in the §20 bucket, where it would
    # eat a saver's allowance it has no claim on.
    assert gains.capital_gains_eur == Decimal(0)


def test_partly_seasoned_crypto_splits_across_the_holding_period(
    client, auth_headers, db_session
):
    """Two lots, one seasoned and one not, sold in a single order — FIFO
    consumes the old lot first and the gain must split accordingly."""
    from app.tax_service import realized_gains_by_regime

    account = _account(client, auth_headers, "Wallet", "CRYPTO_WALLET")
    coin = _instrument(client, auth_headers, "Coin", "XX0000003200", "CRYPTO")
    _txn(
        client, auth_headers, "s-buy-old", date="2023-01-10", type="BUY",
        account_id=account, instrument_id=coin, quantity="1", price="1000.00",
    )
    _txn(
        client, auth_headers, "s-buy-new", date="2024-05-01", type="BUY",
        account_id=account, instrument_id=coin, quantity="1", price="2000.00",
    )
    _txn(
        client, auth_headers, "s-sell", date="2024-08-01", type="SELL",
        account_id=account, instrument_id=coin, quantity="2", price="3000.00",
    )

    gains = _session(lambda db: realized_gains_by_regime(db, 2024))

    # Proceeds 6000 split by quantity: 3000 to each lot.
    # Old lot (2023-01-10, seasoned): 3000 - 1000 = 2000 exempt.
    # New lot (2024-05-01, three months): 3000 - 2000 = 1000 taxable.
    assert gains.private_sale_exempt_eur == Decimal("2000.00")
    assert gains.private_sale_taxable_eur == Decimal("1000.00")


# --------------------------------------------------------------------
# §20 saver's allowance
# --------------------------------------------------------------------


def test_saver_allowance_usage_hand_derived(client, auth_headers, db_session):
    from app.tax_service import saver_allowance_usage

    account, instrument = _setup(client, auth_headers, db_session)
    _txn(
        client, auth_headers, "tax-div-1", date="2024-07-01", type="DIVIDEND",
        account_id=account, instrument_id=instrument, amount="50.00",
    )

    usage = _session(lambda db: saver_allowance_usage(db, 2024, Decimal(1000)))

    assert usage.realized_gains_eur == Decimal("100.00")
    assert usage.investment_income_eur == Decimal("50.00")
    assert usage.vorabpauschale_eur == Decimal(0)
    assert usage.total_eur == Decimal("150.00")
    assert usage.remaining_eur == Decimal("850.00")


def test_vorabpauschale_consumes_the_saver_allowance(client, auth_headers, db_session):
    """The whole reason the entry exists: a January debit that eats the
    allowance before any sale does. Without it every downstream estimate
    is handed headroom that was already spent."""
    from app.tax_service import saver_allowance_usage

    _setup(client, auth_headers, db_session)
    resp = client.post(
        "/api/vorabpauschale",
        json={"year": 2024, "amount_eur": "900.00", "note": "broker statement"},
        headers=auth_headers,
    )
    assert resp.status_code == 201

    usage = _session(lambda db: saver_allowance_usage(db, 2024, Decimal(1000)))

    # 100 realized + 0 income + 900 Vorabpauschale = 1000 -> nothing left.
    assert usage.vorabpauschale_eur == Decimal("900.00")
    assert usage.total_eur == Decimal("1000.00")
    assert usage.remaining_eur == Decimal("0.00")


def test_saver_allowance_ignores_private_sale_gains(client, auth_headers, db_session):
    from app.tax_service import saver_allowance_usage

    account = _account(client, auth_headers, "Wallet", "CRYPTO_WALLET")
    coin = _instrument(client, auth_headers, "Coin", "XX0000003300", "CRYPTO")
    _txn(
        client, auth_headers, "i-buy", date="2024-01-10", type="BUY",
        account_id=account, instrument_id=coin, quantity="1", price="1000.00",
    )
    _txn(
        client, auth_headers, "i-sell", date="2024-03-10", type="SELL",
        account_id=account, instrument_id=coin, quantity="1", price="4000.00",
    )

    usage = _session(lambda db: saver_allowance_usage(db, 2024, Decimal(1000)))

    # A 3000 short-held crypto gain is a §23 matter start to finish. It
    # must leave the §20 allowance completely untouched.
    assert usage.realized_gains_eur == Decimal(0)
    assert usage.remaining_eur == Decimal("1000")


def test_saver_allowance_usage_only_counts_the_given_year(client, auth_headers, db_session):
    from app.tax_service import saver_allowance_usage

    _setup(client, auth_headers, db_session)  # sell is dated 2024-06-01

    usage = _session(lambda db: saver_allowance_usage(db, 2025, Decimal(1000)))

    assert usage.realized_gains_eur == Decimal(0)
    assert usage.total_eur == Decimal(0)


# --------------------------------------------------------------------
# §23 Freigrenze
# --------------------------------------------------------------------


def test_private_sale_freigrenze_is_a_cliff_not_an_allowance(
    client, auth_headers, db_session
):
    """One euro over the limit makes the entire gain taxable — the
    behaviour that separates a Freigrenze from a Freibetrag."""
    from app.tax_service import liquidation_summary

    account = _account(client, auth_headers, "Wallet", "CRYPTO_WALLET")
    coin = _instrument(client, auth_headers, "Coin", "XX0000004100", "CRYPTO")
    _txn(
        client, auth_headers, "f-buy", date="2024-11-01", type="BUY",
        account_id=account, instrument_id=coin, quantity="1", price="1000.00",
    )
    _price(db_session, coin, date(2024, 12, 1), "2001.00")

    over = _session(
        lambda db: liquidation_summary(
            db, personal_tax_rate=Decimal("0.42"), as_of=date(2024, 12, 15)
        )
    )
    # Gain 1001, at or over the 1000 limit -> all 1001 taxable.
    assert over.private_sale.net_gain_eur == Decimal("1001.00")
    assert over.private_sale.taxable_eur == Decimal("1001.00")
    assert over.private_sale.tax_eur == Decimal("1001.00") * Decimal("0.42")

    under = _session(
        lambda db: liquidation_summary(
            db,
            personal_tax_rate=Decimal("0.42"),
            private_sale_exemption_limit_eur=Decimal("1500"),
            as_of=date(2024, 12, 15),
        )
    )
    # Same gain, higher limit -> under the cliff, nothing taxable at all.
    assert under.private_sale.taxable_eur == Decimal(0)
    assert under.private_sale.tax_eur == Decimal(0)


def test_freigrenze_counts_gains_already_realized_this_year(
    client, auth_headers, db_session
):
    """The limit applies to the calendar year's private-sale gains as a
    whole, so a sale that already happened pushes the hypothetical one
    over the edge."""
    from app.tax_service import liquidation_summary

    account = _account(client, auth_headers, "Wallet", "CRYPTO_WALLET")
    coin = _instrument(client, auth_headers, "Coin", "XX0000004200", "CRYPTO")
    _txn(
        client, auth_headers, "g-buy", date="2024-11-01", type="BUY",
        account_id=account, instrument_id=coin, quantity="1", price="1000.00",
    )
    _price(db_session, coin, date(2024, 12, 1), "1600.00")

    alone = _session(
        lambda db: liquidation_summary(
            db, personal_tax_rate=Decimal("0.42"), as_of=date(2024, 12, 15)
        )
    )
    # 600 unrealized on its own stays under 1000.
    assert alone.private_sale.taxable_eur == Decimal(0)

    with_prior = _session(
        lambda db: liquidation_summary(
            db,
            private_sale_realized_taxable_eur=Decimal("500"),
            personal_tax_rate=Decimal("0.42"),
            as_of=date(2024, 12, 15),
        )
    )
    # 600 + 500 already realized = 1100 -> over the cliff. Only the 600
    # still unrealized is taxed here; the 500 was taxed when it happened.
    assert with_prior.private_sale.taxable_eur == Decimal("600.00")


# --------------------------------------------------------------------
# Liquidation summary
# --------------------------------------------------------------------


def test_unrealized_tax_estimate_hand_derived(client, auth_headers, db_session):
    from app.tax_service import liquidation_summary

    _setup(client, auth_headers, db_session)
    # Remaining position after the sell: 5 units, cost basis 500. Mark
    # the price up to 150 -> current value 750, unrealized = 250.
    _price(db_session, 1, date(2024, 12, 1), "150.00")

    no_allowance = _session(
        lambda db: liquidation_summary(db, remaining_allowance_eur=Decimal(0),
                                       as_of=date(2024, 12, 15))
    )
    with_allowance = _session(
        lambda db: liquidation_summary(db, remaining_allowance_eur=Decimal(600),
                                       as_of=date(2024, 12, 15))
    )

    assert len(no_allowance.rows) == 1
    row = no_allowance.rows[0]
    assert row.quantity == Decimal("5")
    assert row.cost_basis_eur == Decimal("500.00")
    assert row.current_value_eur == Decimal("750.00")
    assert row.unrealized_pl_eur == Decimal("250.00")
    # §20: holding period is irrelevant, nothing is tax-free.
    assert row.tax_free_gain_eur == Decimal(0)
    assert row.exposed_gain_eur == Decimal("250.00")
    # 250 * 0.25 * 1.055 = 65.9375
    assert row.estimated_tax_eur == Decimal("250.00") * Decimal("0.25") * Decimal("1.055")

    # Allowance headroom (600) covers the whole 250 gain -> no tax.
    assert with_allowance.rows[0].estimated_tax_eur == Decimal(0)
    assert with_allowance.capital_gains.allowance_applied_eur == Decimal("250.00")


def test_seasoned_crypto_is_not_taxed_on_a_hypothetical_sale(
    client, auth_headers, db_session
):
    """The headline complaint: Bitcoin held over a year shows tax due."""
    from app.models import TaxTreatment
    from app.tax_service import liquidation_summary

    account = _account(client, auth_headers, "Wallet", "CRYPTO_WALLET")
    coin = _instrument(client, auth_headers, "Coin", "XX0000005100", "CRYPTO")
    _txn(
        client, auth_headers, "b-buy", date="2023-01-10", type="BUY",
        account_id=account, instrument_id=coin, quantity="1", price="10000.00",
    )
    _price(db_session, coin, date(2024, 12, 1), "40000.00")

    summary = _session(lambda db: liquidation_summary(db, as_of=date(2024, 12, 15)))

    row = summary.rows[0]
    assert row.tax_treatment is TaxTreatment.PRIVATE_SALE
    assert row.unrealized_pl_eur == Decimal("30000.00")
    # Bought 2023-01-10, "sold" 2024-12-15: well past one year.
    assert row.tax_free_gain_eur == Decimal("30000.00")
    assert row.exposed_gain_eur == Decimal(0)
    assert row.tax_free_quantity == Decimal("1")
    assert row.next_tax_free_date is None
    assert row.estimated_tax_eur == Decimal(0)
    assert summary.total_tax_eur == Decimal("0.00")


def test_lots_are_valued_individually_not_pro_rata(client, auth_headers, db_session):
    """Two lots at different prices: the tax-free share has to come from
    valuing each lot at today's price, not from splitting the aggregate
    gain by quantity."""
    from app.tax_service import liquidation_summary

    account = _account(client, auth_headers, "Wallet", "CRYPTO_WALLET")
    coin = _instrument(client, auth_headers, "Coin", "XX0000005200", "CRYPTO")
    _txn(
        client, auth_headers, "l-old", date="2023-06-01", type="BUY",
        account_id=account, instrument_id=coin, quantity="1", price="1000.00",
    )
    _txn(
        client, auth_headers, "l-new", date="2024-10-01", type="BUY",
        account_id=account, instrument_id=coin, quantity="1", price="4000.00",
    )
    _price(db_session, coin, date(2024, 12, 1), "5000.00")

    summary = _session(lambda db: liquidation_summary(db, as_of=date(2024, 12, 15)))
    row = summary.rows[0]

    # Total: value 10000 - cost 5000 = 5000 unrealized.
    assert row.unrealized_pl_eur == Decimal("5000.00")
    # Old lot: 5000 - 1000 = 4000, seasoned -> free.
    assert row.tax_free_gain_eur == Decimal("4000.00")
    # New lot: 5000 - 4000 = 1000, still inside the year -> exposed.
    # A pro-rata split by quantity would have said 2500/2500.
    assert row.exposed_gain_eur == Decimal("1000.00")
    assert row.tax_free_quantity == Decimal("1")
    assert row.next_tax_free_date == date(2025, 10, 1)


def test_rows_are_sorted_by_tax_owed_descending(client, auth_headers, db_session):
    from app.tax_service import liquidation_summary

    account = _account(client, auth_headers, "Portfolio", "BROKERAGE")
    small = _instrument(client, auth_headers, "Small Gain", "XX0000006100", "EQUITY")
    large = _instrument(client, auth_headers, "Large Gain", "XX0000006200", "EQUITY")
    for eid, iid, price in (("sm", small, "110.00"), ("lg", large, "100.00")):
        _txn(
            client, auth_headers, f"{eid}-buy", date="2024-01-05", type="BUY",
            account_id=account, instrument_id=iid, quantity="10", price=price,
        )
    _price(db_session, small, date(2024, 12, 1), "120.00")   # gain 100
    _price(db_session, large, date(2024, 12, 1), "300.00")   # gain 2000

    summary = _session(lambda db: liquidation_summary(db, as_of=date(2024, 12, 15)))

    assert [r.instrument_id for r in summary.rows] == [large, small]
    assert summary.rows[0].estimated_tax_eur > summary.rows[1].estimated_tax_eur


def test_losses_offset_gains_within_a_regime_and_rows_sum_to_the_total(
    client, auth_headers, db_session
):
    """A full liquidation realizes losses too. Taxing each winner alone
    (the old per-position behaviour) overstates the bill."""
    from app.tax_service import liquidation_summary

    account = _account(client, auth_headers, "Portfolio", "BROKERAGE")
    winner = _instrument(client, auth_headers, "Winner", "XX0000007100", "EQUITY")
    loser = _instrument(client, auth_headers, "Loser", "XX0000007200", "EQUITY")
    for eid, iid in (("w", winner), ("l", loser)):
        _txn(
            client, auth_headers, f"{eid}-buy", date="2024-01-05", type="BUY",
            account_id=account, instrument_id=iid, quantity="10", price="100.00",
        )
    _price(db_session, winner, date(2024, 12, 1), "200.00")  # +1000
    _price(db_session, loser, date(2024, 12, 1), "40.00")    # -600

    summary = _session(lambda db: liquidation_summary(db, as_of=date(2024, 12, 15)))

    assert summary.capital_gains.gross_gain_eur == Decimal("1000.00")
    assert summary.capital_gains.losses_eur == Decimal("600.00")
    assert summary.capital_gains.net_gain_eur == Decimal("400.00")
    # 400 * 0.25 * 1.055 = 105.50
    assert summary.capital_gains.tax_eur == Decimal("105.50")
    # The loser carries no tax; the winner carries all of it, and the
    # rows add back up to the headline figure exactly.
    by_id = {r.instrument_id: r for r in summary.rows}
    assert by_id[loser].estimated_tax_eur == Decimal(0)
    assert by_id[winner].estimated_tax_eur == Decimal("105.50")
    assert sum(r.estimated_tax_eur for r in summary.rows) == summary.total_tax_eur


def test_summary_totals_and_net_proceeds(client, auth_headers, db_session):
    from app.tax_service import liquidation_summary

    _setup(client, auth_headers, db_session)
    _price(db_session, 1, date(2024, 12, 1), "150.00")

    summary = _session(lambda db: liquidation_summary(db, as_of=date(2024, 12, 15)))

    assert summary.total_current_value_eur == Decimal("750.00")
    assert summary.total_cost_basis_eur == Decimal("500.00")
    assert summary.total_unrealized_pl_eur == Decimal("250.00")
    # 250 * 0.25 * 1.055 = 65.9375 -> 65.94 quantized.
    assert summary.total_tax_eur == Decimal("65.94")
    assert summary.net_proceeds_eur == Decimal("750.00") - Decimal("65.94")


def test_positions_without_a_market_price_are_excluded_not_guessed(
    client, auth_headers, db_session
):
    from app.tax_service import liquidation_summary

    account = _account(client, auth_headers, "Portfolio", "BROKERAGE")
    priced = _instrument(client, auth_headers, "Priced", "XX0000008100", "EQUITY")
    unpriced = _instrument(client, auth_headers, "Unpriced", "XX0000008200", "EQUITY")
    for eid, iid in (("p", priced), ("u", unpriced)):
        _txn(
            client, auth_headers, f"{eid}-buy", date="2024-01-05", type="BUY",
            account_id=account, instrument_id=iid, quantity="10", price="100.00",
        )
    _price(db_session, priced, date(2024, 12, 1), "150.00")

    summary = _session(lambda db: liquidation_summary(db, as_of=date(2024, 12, 15)))

    assert len(summary.rows) == 1
    assert summary.excluded_position_count == 1


# --------------------------------------------------------------------
# Vorabpauschale entry + reminder
# --------------------------------------------------------------------


def test_vorabpauschale_upsert_replaces_rather_than_duplicates(client, auth_headers):
    first = client.post(
        "/api/vorabpauschale", json={"year": 2025, "amount_eur": "120.00"},
        headers=auth_headers,
    )
    assert first.status_code == 201
    second = client.post(
        "/api/vorabpauschale", json={"year": 2025, "amount_eur": "145.50"},
        headers=auth_headers,
    )
    assert second.status_code == 201

    listed = client.get("/api/vorabpauschale", headers=auth_headers).json()
    assert len(listed) == 1
    assert listed[0]["amount_eur"] == "145.50"


def test_vorabpauschale_delete(client, auth_headers):
    client.post(
        "/api/vorabpauschale", json={"year": 2025, "amount_eur": "120.00"},
        headers=auth_headers,
    )
    assert client.delete("/api/vorabpauschale/2025", headers=auth_headers).status_code == 204
    assert client.delete("/api/vorabpauschale/2025", headers=auth_headers).status_code == 404
    assert client.get("/api/vorabpauschale", headers=auth_headers).json() == []


def test_vorabpauschale_requires_write_scope(client):
    assert client.post("/api/vorabpauschale", json={"year": 2025, "amount_eur": "1"}).status_code == 401


def test_vorabpauschale_reminder_only_in_january_with_holdings(
    client, auth_headers, db_session
):
    from app.tax_service import vorabpauschale_reminder

    _setup(client, auth_headers, db_session)

    january = _session(lambda db: vorabpauschale_reminder(db, as_of=date(2025, 1, 15)))
    june = _session(lambda db: vorabpauschale_reminder(db, as_of=date(2025, 6, 15)))

    assert january is not None
    assert "Test ETF" in january
    assert june is None


def test_vorabpauschale_reminder_stops_once_the_amount_is_entered(
    client, auth_headers, db_session
):
    """A reminder that survives being acted on is just noise."""
    from app.tax_service import vorabpauschale_reminder

    _setup(client, auth_headers, db_session)
    client.post(
        "/api/vorabpauschale", json={"year": 2025, "amount_eur": "88.00"},
        headers=auth_headers,
    )

    assert _session(lambda db: vorabpauschale_reminder(db, as_of=date(2025, 1, 15))) is None


def test_vorabpauschale_reminder_none_without_holdings(client, auth_headers, db_session):
    from app.tax_service import vorabpauschale_reminder

    assert _session(lambda db: vorabpauschale_reminder(db, as_of=date(2025, 1, 15))) is None


def test_vorabpauschale_reminder_ignores_crypto_only_portfolios(
    client, auth_headers, db_session
):
    """The advance lump sum is a fund mechanism. A wallet full of coins
    has nothing it could apply to."""
    from app.tax_service import vorabpauschale_reminder

    account = _account(client, auth_headers, "Wallet", "CRYPTO_WALLET")
    coin = _instrument(client, auth_headers, "Coin", "XX0000009100", "CRYPTO")
    _txn(
        client, auth_headers, "v-buy", date="2024-01-10", type="BUY",
        account_id=account, instrument_id=coin, quantity="1", price="1000.00",
    )

    assert _session(lambda db: vorabpauschale_reminder(db, as_of=date(2025, 1, 15))) is None


# --------------------------------------------------------------------
# Endpoint
# --------------------------------------------------------------------


def test_tax_overview_endpoint_end_to_end(client, auth_headers, db_session):
    _setup(client, auth_headers, db_session)
    _price(db_session, 1, date(2024, 12, 1), "150.00")

    resp = client.get(
        "/api/tax", params={"year": 2024, "allowance": "1000"}, headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["saver_allowance"]["realized_gains_eur"] == "100.00"
    assert body["saver_allowance"]["vorabpauschale_eur"] == "0"
    assert body["private_sale_allowance"]["realized_taxable_eur"] == "0"
    assert len(body["unrealized"]) == 1
    assert body["unrealized"][0]["unrealized_pl_eur"] == "250.00"
    assert body["unrealized"][0]["tax_treatment"] == "CAPITAL_GAINS"
    assert body["liquidation"]["total_current_value_eur"] == "750.00"
    assert body["vorabpauschale"] is None
    assert body["vorabpauschale_reminder"] is None  # default "today" isn't January


def test_tax_overview_reports_the_entered_vorabpauschale(client, auth_headers, db_session):
    _setup(client, auth_headers, db_session)
    client.post(
        "/api/vorabpauschale",
        json={"year": 2024, "amount_eur": "310.25", "note": "from statement"},
        headers=auth_headers,
    )

    body = client.get(
        "/api/tax", params={"year": 2024, "allowance": "1000"}, headers=auth_headers
    ).json()

    assert body["vorabpauschale"]["amount_eur"] == "310.25"
    assert body["vorabpauschale"]["note"] == "from statement"
    # 100 realized + 310.25 -> 589.75 left of the 1000.
    assert body["saver_allowance"]["remaining_eur"] == "589.75"


def test_tax_overview_rejects_an_out_of_range_personal_rate(client, auth_headers):
    resp = client.get(
        "/api/tax", params={"personal_tax_rate": "1.5"}, headers=auth_headers
    )
    assert resp.status_code == 422


def test_tax_overview_endpoint_requires_auth(client):
    resp = client.get("/api/tax")
    assert resp.status_code == 401
