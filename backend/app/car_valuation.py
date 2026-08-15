"""Car depreciation model (spec 3.3). Pure function, no I/O — tested
against hand-computed numbers before anything else touches it, per
AGENTS.md's rule for anything that calculates.

Interpreting one genuinely ambiguous sentence in the spec: "for a used
purchase, the starting value is the purchase price rather than the list
price, and the effective vehicle age is derived from the first
registration — otherwise the model double-counts the depreciation already
suffered." Taken completely literally (substitute purchase_price for
list_price *and* use age-since-registration as the exponential-decay
clock) would re-apply `initial_drop` and years of decay that are already
priced into what was actually paid for a used car — which is exactly the
double-counting the sentence warns against, not a fix for it.

The reading implemented here: `initial_drop` (the one-time registration-
loss) only applies to a genuinely new purchase (first_registration ==
purchase_date). The exponential decay clock runs from the *purchase* date
forward either way — so a used car's already-suffered depreciation is
never re-applied, only what happens after you owned it. "Age since first
registration" is used for the one place spec's own km_penalty formula
needs a car's true age: the 15,000 km/year expected-mileage baseline,
which has to reflect how old the car really is, not just how long you've
owned it. Flagged to the user rather than silently assumed — spec's own
"even a 25% model error moves the total by well under one percent" is
why this is a documented interpretation rather than a blocking question.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

DEFAULT_INITIAL_DROP = Decimal("0.20")
DEFAULT_K = Decimal("0.13")
DEFAULT_FLOOR_PCT = Decimal("0.10")
KM_PENALTY_RATE = Decimal("0.08")
EXPECTED_KM_PER_YEAR = Decimal(15000)
KM_PENALTY_DIVISOR = Decimal(100000)
DAYS_PER_YEAR = Decimal("365.25")


@dataclass
class CarValuationConfig:
    purchase_price_eur: Decimal
    purchase_date: date
    first_registration: date
    mileage_at_purchase_km: Decimal
    annual_mileage_estimate_km: Decimal
    initial_drop: Decimal = DEFAULT_INITIAL_DROP
    k: Decimal = DEFAULT_K
    floor_pct: Decimal = DEFAULT_FLOOR_PCT


def _years_between(start: date, end: date) -> Decimal:
    return max(Decimal(0), Decimal((end - start).days) / DAYS_PER_YEAR)


def car_residual_value(config: CarValuationConfig, as_of: date) -> Decimal:
    if as_of < config.purchase_date:
        return config.purchase_price_eur

    t_since_purchase = _years_between(config.purchase_date, as_of)
    t_since_registration = _years_between(config.first_registration, as_of)

    total_driven_km = (
        config.mileage_at_purchase_km + config.annual_mileage_estimate_km * t_since_purchase
    )
    expected_km = EXPECTED_KM_PER_YEAR * t_since_registration
    km_penalty = max(Decimal(0), (total_driven_km - expected_km) / KM_PENALTY_DIVISOR) * KM_PENALTY_RATE

    is_new_purchase = config.first_registration == config.purchase_date
    initial_drop_factor = (1 - config.initial_drop) if is_new_purchase else Decimal(1)

    # Decimal has no native exp(); float precision here is fine — this is
    # a depreciation *estimate* by design, never money in the exact-ledger
    # sense the rest of the app holds itself to.
    decay = Decimal(str(pow(2.718281828459045, float(-config.k * t_since_purchase))))

    modeled = (
        config.purchase_price_eur * initial_drop_factor * decay * (1 - km_penalty)
    )
    floor = config.floor_pct * config.purchase_price_eur
    return max(floor, modeled)
