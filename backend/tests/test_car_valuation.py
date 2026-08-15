"""spec 3.3, golden numbers computed by hand (or accepted with a small
tolerance where the model's own exp() introduces float imprecision by
design — see app/car_valuation.py's module docstring for why)."""

from datetime import date
from decimal import Decimal

from app.car_valuation import CarValuationConfig, car_residual_value

TOLERANCE = Decimal("0.5")


def _new_car(**overrides) -> CarValuationConfig:
    defaults = dict(
        purchase_price_eur=Decimal("20000.00"),
        purchase_date=date(2024, 1, 1),
        first_registration=date(2024, 1, 1),
        mileage_at_purchase_km=Decimal(0),
        annual_mileage_estimate_km=Decimal(15000),
    )
    defaults.update(overrides)
    return CarValuationConfig(**defaults)


def test_new_car_loses_registration_drop_immediately():
    config = _new_car()
    # t=0: exp(0)=1, no mileage penalty yet -> exactly (1 - initial_drop)
    residual = car_residual_value(config, date(2024, 1, 1))
    assert residual == Decimal("16000.00")  # 20000 * 0.80


def test_new_car_after_one_year_on_expected_mileage():
    config = _new_car()
    residual = car_residual_value(config, date(2025, 1, 1))
    # 20000 * 0.80 * exp(-0.13) ~ 14049.5. 2024 is a leap year, so 366
    # actual days over the 365.25-day approximation shifts this by a few
    # euros — a real, expected effect of the day-count approximation, not
    # a bug, hence the wider tolerance than the other, exact-day tests.
    assert abs(residual - Decimal("14049.5")) < Decimal("10")


def test_high_mileage_adds_a_penalty():
    config = _new_car(annual_mileage_estimate_km=Decimal(30000))  # double the baseline
    with_penalty = car_residual_value(config, date(2025, 1, 1))
    without_penalty = car_residual_value(_new_car(), date(2025, 1, 1))
    assert with_penalty < without_penalty


def test_value_floors_rather_than_approaching_zero():
    config = _new_car()
    residual = car_residual_value(config, date(2044, 1, 1))  # 20 years out
    assert residual == Decimal("2000.00")  # floor_pct 0.10 * 20000


def test_used_purchase_does_not_reapply_the_registration_drop():
    # bought 2 years after first registration — the previous owner already
    # absorbed the registration-loss; the purchase price already reflects
    # it, so the model must not knock another 20% off on top.
    config = CarValuationConfig(
        purchase_price_eur=Decimal("14000.00"),
        purchase_date=date(2024, 1, 1),
        first_registration=date(2022, 1, 1),
        mileage_at_purchase_km=Decimal(30000),
        annual_mileage_estimate_km=Decimal(15000),
    )
    at_purchase = car_residual_value(config, date(2024, 1, 1))
    # Not exactly 14000.00: the 730-day gap divided by the 365.25-day
    # approximation isn't exactly 2 years, so the km-penalty baseline
    # picks up a trace mismatch against the real odometer reading — a
    # real day-count effect, not a reintroduced registration-drop (which
    # would be a ~20% difference, not a few cents).
    assert abs(at_purchase - Decimal("14000.00")) < Decimal("1.00")


def test_used_purchase_value_before_purchase_date_holds_the_price():
    config = CarValuationConfig(
        purchase_price_eur=Decimal("14000.00"),
        purchase_date=date(2024, 1, 1),
        first_registration=date(2022, 1, 1),
        mileage_at_purchase_km=Decimal(30000),
        annual_mileage_estimate_km=Decimal(15000),
    )
    assert car_residual_value(config, date(2023, 1, 1)) == Decimal("14000.00")
