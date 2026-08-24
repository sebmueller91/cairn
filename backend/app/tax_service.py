"""Tax-informational view (spec 4.6, explicitly non-binding — not tax
advice).

German private investors fall under two different regimes and the
difference is not cosmetic:

* **§20 EStG (Kapitalvermögen)** — shares, ETFs, bonds, dividends,
  interest. Flat Abgeltungsteuer plus solidarity surcharge, holding
  period irrelevant, offset against the annual *Sparerpauschbetrag*
  (a genuine allowance: only the excess is taxed).

* **§23 EStG (Privatveräußerungsgeschäft)** — crypto, physical precious
  metals, property. **Tax-free once held beyond the speculation period**
  (one year; ten for property). Inside the period the gain is taxed at
  the *personal* income tax rate, not the flat 25%, and is measured
  against a separate *Freigrenze* — a cliff, not an allowance: one euro
  over the limit makes the entire amount taxable.

Everything here is an estimate for orientation. The simplifications are
listed on `LiquidationSummary`, not buried.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db_types import quantize_money
from app.ledger import RealizedSale, add_years, holding_period_elapsed, replay, txn_to_event
from app.models import (
    AssetClass,
    Instrument,
    TaxTreatment,
    TransactionType,
    Txn,
    ValuationMode,
    VorabpauschaleEntry,
)
from app.valuation_service import current_instrument_value

# Germany's flat capital-gains tax (Abgeltungsteuer) + solidarity
# surcharge — a reasonable illustrative default, not this year's
# authoritative rate; church tax varies by state and isn't modeled.
DEFAULT_CAPITAL_GAINS_TAX_RATE = Decimal("0.25")
DEFAULT_SOLIDARITY_SURCHARGE_RATE = Decimal("0.055")  # of the tax amount, not of the gain

# §23 gains are taxed at the personal marginal rate. Defaulting to the
# Spitzensteuersatz deliberately over-states rather than under-states:
# a planning view that quietly promises too little tax is the worse
# failure. Overridable per request — a rate this specific to one person
# has no business being a constant.
DEFAULT_PERSONAL_INCOME_TAX_RATE = Decimal("0.42")

# The solidarity surcharge still rides on top of income tax, but only
# above a threshold that most filers stay under since 2021, so it is
# deliberately NOT applied to the §23 leg. Applying it to everyone
# would be wrong more often than right.

# §23 Abs. 3 Satz 5 EStG: total private-sale gains in a calendar year
# below this stay free; at or above it, the *whole* amount is taxable.
DEFAULT_PRIVATE_SALE_EXEMPTION_LIMIT_EUR = Decimal("1000")

# §23 speculation periods in whole years, by asset class. Anything not
# listed that still resolves to PRIVATE_SALE uses one year.
_SPECULATION_PERIOD_YEARS: dict[AssetClass, int] = {
    AssetClass.REAL_ESTATE: 10,
}
DEFAULT_SPECULATION_PERIOD_YEARS = 1

# Which regime an asset class falls under absent an explicit override on
# the instrument. VEHICLE/CASH/LIABILITY resolve to NONE: not a claim
# that selling a car can never be taxable, a claim that Cairn will not
# put a number on it.
_DEFAULT_TREATMENT: dict[AssetClass, TaxTreatment] = {
    AssetClass.EQUITY: TaxTreatment.CAPITAL_GAINS,
    AssetClass.BOND: TaxTreatment.CAPITAL_GAINS,
    AssetClass.CRYPTO: TaxTreatment.PRIVATE_SALE,
    AssetClass.COMMODITY: TaxTreatment.PRIVATE_SALE,
    AssetClass.REAL_ESTATE: TaxTreatment.PRIVATE_SALE,
    AssetClass.VEHICLE: TaxTreatment.NONE,
    AssetClass.CASH: TaxTreatment.NONE,
    AssetClass.LIABILITY: TaxTreatment.NONE,
}


def tax_treatment_of(instrument: Instrument) -> TaxTreatment:
    """The instrument's explicit override if set, otherwise the default
    for its asset class.

    The override exists because asset_class genuinely cannot decide some
    real cases: a physically-backed gold ETC carrying a delivery claim is
    a §23 private sale (BFH), a swap-based ETC tracking the same metal is
    §20. Guessing between them from the data on hand would be inventing a
    domain rule."""
    if instrument.tax_treatment is not None:
        return instrument.tax_treatment
    return _DEFAULT_TREATMENT.get(instrument.asset_class, TaxTreatment.CAPITAL_GAINS)


def speculation_period_years(instrument: Instrument) -> int:
    return _SPECULATION_PERIOD_YEARS.get(
        instrument.asset_class, DEFAULT_SPECULATION_PERIOD_YEARS
    )


def _instruments_by_id(db: Session) -> dict[int, Instrument]:
    return {i.id: i for i in db.query(Instrument).all()}


def _ledger(db: Session):
    txns = db.query(Txn).filter(Txn.voided_at.is_(None), Txn.instrument_id.isnot(None)).all()
    return replay([txn_to_event(t) for t in txns])


def realized_sales(db: Session) -> list[RealizedSale]:
    """Every SELL with the FIFO lots it consumed, in ledger order.

    This used to be a second, independent FIFO replay living in this
    module — two implementations of the same rule, which is exactly the
    kind of divergence that produces a quietly wrong number. It is now
    one call into `app.ledger`, the single ledger authority, which also
    means each sale arrives carrying its lots' acquisition dates and can
    therefore be split by holding period at all."""
    return _ledger(db).sales


@dataclass
class RegimeGains:
    """Realized gains for one calendar year, already split by regime."""

    capital_gains_eur: Decimal = Decimal(0)
    private_sale_exempt_eur: Decimal = Decimal(0)
    private_sale_taxable_eur: Decimal = Decimal(0)


def realized_gains_by_regime(db: Session, year: int) -> RegimeGains:
    instruments = _instruments_by_id(db)
    result = RegimeGains()
    for sale in realized_sales(db):
        if sale.date.year != year:
            continue
        instrument = instruments.get(sale.instrument_id)
        if instrument is None:
            continue
        treatment = tax_treatment_of(instrument)
        if treatment is TaxTreatment.CAPITAL_GAINS:
            result.capital_gains_eur += sale.gain_eur
        elif treatment is TaxTreatment.PRIVATE_SALE:
            exempt, taxable = sale.gain_split_by_holding_period(
                speculation_period_years(instrument)
            )
            result.private_sale_exempt_eur += exempt
            result.private_sale_taxable_eur += taxable
    return result


def vorabpauschale_for(db: Session, year: int) -> VorabpauschaleEntry | None:
    return db.get(VorabpauschaleEntry, year)


@dataclass
class SaverAllowance:
    """§20 Sparerpauschbetrag usage for one calendar year."""

    year: int
    allowance_eur: Decimal
    realized_gains_eur: Decimal
    investment_income_eur: Decimal
    vorabpauschale_eur: Decimal
    total_eur: Decimal
    remaining_eur: Decimal


def saver_allowance_usage(db: Session, year: int, allowance_eur: Decimal) -> SaverAllowance:
    """What has already eaten this year's §20 allowance.

    Three things do, and the Vorabpauschale is the one most easily
    forgotten: it is deemed investment income under §20, it is debited in
    the first days of January, and for a portfolio of accumulating funds
    it can consume the entire Sparerpauschbetrag before any actual sale
    happens. Leaving it out makes every downstream "tax if you sold
    today" figure too low, because it hands the estimate headroom that
    was spent in January."""
    gains = realized_gains_by_regime(db, year)
    income_txns = (
        db.query(Txn)
        .filter(
            Txn.voided_at.is_(None),
            Txn.type.in_([TransactionType.DIVIDEND, TransactionType.INTEREST]),
            Txn.date >= date(year, 1, 1),
            Txn.date <= date(year, 12, 31),
        )
        .all()
    )
    income = sum((t.amount_eur for t in income_txns), Decimal(0))
    entry = vorabpauschale_for(db, year)
    vorab = entry.amount_eur if entry else Decimal(0)
    total = gains.capital_gains_eur + income + vorab
    return SaverAllowance(
        year=year,
        allowance_eur=allowance_eur,
        realized_gains_eur=gains.capital_gains_eur,
        investment_income_eur=income,
        vorabpauschale_eur=vorab,
        total_eur=total,
        remaining_eur=allowance_eur - total,
    )


@dataclass
class PrivateSaleAllowance:
    """§23 Freigrenze usage for one calendar year.

    Deliberately a separate figure from the Sparerpauschbetrag rather
    than a second number in the same card: they are different rules with
    different mechanics, and treating crypto gains as if they consumed
    the saver's allowance (which the previous version did) is wrong in
    both directions at once — it burns §20 headroom that is still there
    and hides the §23 cliff that is about to be crossed."""

    year: int
    exemption_limit_eur: Decimal
    realized_taxable_eur: Decimal
    realized_exempt_eur: Decimal
    remaining_eur: Decimal
    limit_exceeded: bool


def private_sale_allowance_usage(
    db: Session,
    year: int,
    exemption_limit_eur: Decimal = DEFAULT_PRIVATE_SALE_EXEMPTION_LIMIT_EUR,
) -> PrivateSaleAllowance:
    gains = realized_gains_by_regime(db, year)
    taxable = gains.private_sale_taxable_eur
    return PrivateSaleAllowance(
        year=year,
        exemption_limit_eur=exemption_limit_eur,
        realized_taxable_eur=taxable,
        realized_exempt_eur=gains.private_sale_exempt_eur,
        remaining_eur=exemption_limit_eur - taxable,
        limit_exceeded=taxable >= exemption_limit_eur,
    )


@dataclass
class UnrealizedTaxEstimate:
    account_id: int
    instrument_id: int
    tax_treatment: TaxTreatment
    quantity: Decimal
    cost_basis_eur: Decimal
    current_value_eur: Decimal
    unrealized_pl_eur: Decimal
    # For §23 positions: the part of the gain sitting in lots already
    # past the speculation period, which no sale today would be taxed
    # on. Always zero under §20, where holding period means nothing.
    tax_free_gain_eur: Decimal
    # The part a sale today would actually expose, before any allowance
    # or Freigrenze is applied. Negative for a position at a loss.
    exposed_gain_eur: Decimal
    tax_free_quantity: Decimal
    # When the earliest still-locked lot clears the speculation period —
    # the "wait until this date" answer. None when nothing is locked.
    next_tax_free_date: date | None
    estimated_tax_eur: Decimal = Decimal(0)


@dataclass
class RegimeLiquidation:
    """One regime's leg of a hypothetical full liquidation."""

    gross_gain_eur: Decimal = Decimal(0)
    losses_eur: Decimal = Decimal(0)
    net_gain_eur: Decimal = Decimal(0)
    allowance_applied_eur: Decimal = Decimal(0)
    taxable_eur: Decimal = Decimal(0)
    tax_eur: Decimal = Decimal(0)
    tax_free_gain_eur: Decimal = Decimal(0)


@dataclass
class LiquidationSummary:
    """"What would I owe if I sold everything right now."

    Known simplifications, all of which can move the real figure:
      * Gains and losses are netted within each regime, in one pot each.
        The real §20 rules keep a separate Verlusttopf for individual
        shares whose losses only offset share gains.
      * No church tax; no solidarity surcharge on the §23 leg.
      * Positions without a market price are excluded entirely and
        counted in `excluded_position_count` rather than guessed at.
      * Selling everything at once is assumed to leave the personal
        income tax rate unchanged, which a large §23 gain would not.
    """

    as_of: date
    total_current_value_eur: Decimal
    total_cost_basis_eur: Decimal
    total_unrealized_pl_eur: Decimal
    capital_gains: RegimeLiquidation
    private_sale: RegimeLiquidation
    total_tax_eur: Decimal
    net_proceeds_eur: Decimal
    excluded_position_count: int
    rows: list[UnrealizedTaxEstimate] = field(default_factory=list)


def _apportion(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Splits `total` across `weights` proportionally, giving the last
    non-zero weight whatever the division left over so the parts sum
    back to `total` exactly."""
    weight_sum = sum(weights, Decimal(0))
    if weight_sum <= 0:
        return [Decimal(0) for _ in weights]
    shares = [Decimal(0) for _ in weights]
    last = max(i for i, w in enumerate(weights) if w > 0)
    assigned = Decimal(0)
    for i, w in enumerate(weights):
        if w <= 0 or i == last:
            continue
        shares[i] = total * w / weight_sum
        assigned += shares[i]
    shares[last] = total - assigned
    return shares


def liquidation_summary(
    db: Session,
    remaining_allowance_eur: Decimal = Decimal(0),
    private_sale_realized_taxable_eur: Decimal = Decimal(0),
    tax_rate: Decimal = DEFAULT_CAPITAL_GAINS_TAX_RATE,
    solidarity_rate: Decimal = DEFAULT_SOLIDARITY_SURCHARGE_RATE,
    personal_tax_rate: Decimal = DEFAULT_PERSONAL_INCOME_TAX_RATE,
    private_sale_exemption_limit_eur: Decimal = DEFAULT_PRIVATE_SALE_EXEMPTION_LIMIT_EUR,
    as_of: date | None = None,
) -> LiquidationSummary:
    """Sells every open position on paper and prices the tax bill.

    Runs regime-wide rather than position-by-position, which the previous
    per-row version could not do: an allowance, a Freigrenze and loss
    offsetting are all properties of the *year's total*, not of a single
    holding. Each row's `estimated_tax_eur` is therefore its share of its
    regime's tax, apportioned by exposed gain — so a row at a loss shows
    no tax (it is already pulling the total down) and the rows always sum
    to the headline figure exactly."""
    as_of = as_of or date.today()
    positions = _ledger(db).positions
    instruments = _instruments_by_id(db)

    rows: list[UnrealizedTaxEstimate] = []
    excluded = 0
    total_value = Decimal(0)
    total_cost = Decimal(0)

    for (account_id, instrument_id), pos in sorted(positions.items()):
        if pos.quantity == 0:
            continue
        instrument = instruments.get(instrument_id)
        if instrument is None or instrument.valuation_mode != ValuationMode.MARKET:
            excluded += 1
            continue
        price = current_instrument_value(db, instrument_id, as_of)
        if price is None:
            excluded += 1
            continue

        treatment = tax_treatment_of(instrument)
        current_value = pos.quantity * price
        unrealized = current_value - pos.cost_basis_eur
        total_value += current_value
        total_cost += pos.cost_basis_eur

        tax_free_gain = Decimal(0)
        tax_free_qty = Decimal(0)
        next_free: date | None = None

        if treatment is TaxTreatment.PRIVATE_SALE:
            # Value each lot at today's price and ask, lot by lot,
            # whether a sale today would fall outside the speculation
            # period. Splitting the aggregate gain pro rata instead
            # would be wrong whenever the lots were bought at different
            # prices, which is the normal case for anyone buying
            # monthly.
            years = speculation_period_years(instrument)
            for lot in pos.lots:
                lot_gain = lot.quantity * price - lot.total_cost_eur
                if holding_period_elapsed(lot.acquired_date, as_of, years):
                    tax_free_gain += lot_gain
                    tax_free_qty += lot.quantity
                else:
                    free_on = add_years(lot.acquired_date, years)
                    if next_free is None or free_on < next_free:
                        next_free = free_on
        elif treatment is TaxTreatment.NONE:
            # Not modeled: the whole gain is reported, none of it exposed.
            tax_free_gain = unrealized
            tax_free_qty = pos.quantity

        rows.append(
            UnrealizedTaxEstimate(
                account_id=account_id,
                instrument_id=instrument_id,
                tax_treatment=treatment,
                quantity=pos.quantity,
                cost_basis_eur=pos.cost_basis_eur,
                current_value_eur=current_value,
                unrealized_pl_eur=unrealized,
                tax_free_gain_eur=tax_free_gain,
                exposed_gain_eur=unrealized - tax_free_gain,
                tax_free_quantity=tax_free_qty,
                next_tax_free_date=next_free,
            )
        )

    cap = RegimeLiquidation()
    priv = RegimeLiquidation()
    for row in rows:
        bucket = cap if row.tax_treatment is TaxTreatment.CAPITAL_GAINS else priv
        bucket.tax_free_gain_eur += row.tax_free_gain_eur
        if row.exposed_gain_eur >= 0:
            bucket.gross_gain_eur += row.exposed_gain_eur
        else:
            bucket.losses_eur += -row.exposed_gain_eur

    # §20: allowance is a true allowance — only the excess is taxed.
    cap.net_gain_eur = cap.gross_gain_eur - cap.losses_eur
    cap.allowance_applied_eur = min(
        max(cap.net_gain_eur, Decimal(0)), max(remaining_allowance_eur, Decimal(0))
    )
    cap.taxable_eur = max(cap.net_gain_eur - cap.allowance_applied_eur, Decimal(0))
    cap.tax_eur = cap.taxable_eur * tax_rate * (Decimal(1) + solidarity_rate)

    # §23: the Freigrenze is a cliff on the *year's* private-sale gains,
    # so gains already realized this year count towards it. Clear the
    # limit and the whole amount is taxable, not just the excess.
    priv.net_gain_eur = priv.gross_gain_eur - priv.losses_eur
    year_total = max(priv.net_gain_eur, Decimal(0)) + max(
        private_sale_realized_taxable_eur, Decimal(0)
    )
    if year_total < private_sale_exemption_limit_eur:
        priv.allowance_applied_eur = max(priv.net_gain_eur, Decimal(0))
        priv.taxable_eur = Decimal(0)
    else:
        priv.allowance_applied_eur = Decimal(0)
        priv.taxable_eur = max(priv.net_gain_eur, Decimal(0))
    priv.tax_eur = priv.taxable_eur * personal_tax_rate

    for bucket in (cap, priv):
        member = [r for r in rows if (r.tax_treatment is TaxTreatment.CAPITAL_GAINS) == (bucket is cap)]
        weights = [max(r.exposed_gain_eur, Decimal(0)) for r in member]
        for row, share in zip(member, _apportion(bucket.tax_eur, weights)):
            row.estimated_tax_eur = share

    # Most tax first — the question this view exists to answer is "what
    # is this going to cost me", and the answer is at the top.
    rows.sort(key=lambda r: (-r.estimated_tax_eur, -r.exposed_gain_eur))

    total_tax = cap.tax_eur + priv.tax_eur
    return LiquidationSummary(
        as_of=as_of,
        total_current_value_eur=quantize_money(total_value),
        total_cost_basis_eur=quantize_money(total_cost),
        total_unrealized_pl_eur=quantize_money(total_value - total_cost),
        capital_gains=cap,
        private_sale=priv,
        total_tax_eur=quantize_money(total_tax),
        net_proceeds_eur=quantize_money(total_value - total_tax),
        excluded_position_count=excluded,
        rows=rows,
    )


def vorabpauschale_reminder(db: Session, as_of: date | None = None) -> str | None:
    """spec 4.6: "a reminder about the January advance lump sum".

    Cairn still does not calculate it. Not for want of the Basiszins —
    the BMF publishes that annually under § 18 Abs. 4 InvStG — but
    because the amount also turns on each fund's Teilfreistellung class,
    which is not modelled here. What changed is that there is now
    somewhere to *put* the figure once the broker states it
    (`vorabpauschale_entry`), so the reminder points at a specific
    action instead of trailing off. Shown in January, and only while
    the year's amount is still missing — a reminder that survives being
    acted on is just noise."""
    as_of = as_of or date.today()
    if as_of.month != 1:
        return None
    if vorabpauschale_for(db, as_of.year) is not None:
        return None
    positions = _ledger(db).positions
    instruments = _instruments_by_id(db)
    names = sorted(
        {
            instruments[iid].name
            for (_, iid), pos in positions.items()
            if pos.quantity != 0
            and iid in instruments
            and instruments[iid].valuation_mode == ValuationMode.MARKET
            and tax_treatment_of(instruments[iid]) is TaxTreatment.CAPITAL_GAINS
        }
    )
    if not names:
        return None
    return (
        "January: your broker debits the Vorabpauschale (advance lump sum) for "
        "accumulating funds now (" + ", ".join(names) + ") and it consumes this "
        "year's saver's allowance before any sale does. Cairn doesn't calculate it "
        "(the amount depends on each fund's Teilfreistellung, which isn't tracked "
        "here) — enter the figure from your statement, which is exact, so the "
        "allowance numbers below are right."
    )
