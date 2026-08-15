"""spec 3.5, hand-computed golden numbers. Invented figures only."""

from datetime import date
from decimal import Decimal

from app.loan_service import LoanConfig, loan_balance, loan_to_value


def _config(**overrides) -> LoanConfig:
    defaults = dict(
        principal=Decimal("100000.00"),
        annual_rate_pct=Decimal("6.0"),  # -> 0.5% monthly
        start_date=date(2024, 1, 1),
        monthly_payment=Decimal("1000.00"),
        extra_repayments=[],
    )
    defaults.update(overrides)
    return LoanConfig(**defaults)


def test_balance_at_start_is_the_principal():
    config = _config()
    assert loan_balance(config, date(2024, 1, 1)) == Decimal("100000.00")


def test_balance_after_one_month():
    config = _config()
    # 100000 * 1.005 - 1000 = 99500.00
    assert loan_balance(config, date(2024, 2, 1)) == Decimal("99500.00")


def test_balance_after_two_months():
    config = _config()
    # 99500 * 1.005 - 1000 = 98997.50
    assert loan_balance(config, date(2024, 3, 1)) == Decimal("98997.50")


def test_extra_repayment_reduces_balance_in_its_month():
    config = _config(extra_repayments=[(date(2024, 1, 20), Decimal("5000.00"))])
    # same as the one-month case, minus the overpayment
    assert loan_balance(config, date(2024, 2, 1)) == Decimal("94500.00")


def test_extra_repayment_compounds_into_later_months():
    with_extra = _config(extra_repayments=[(date(2024, 1, 20), Decimal("5000.00"))])
    without_extra = _config()
    later = date(2024, 6, 1)
    assert loan_balance(with_extra, later) < loan_balance(without_extra, later)


def test_balance_never_goes_negative_once_paid_off():
    config = _config(monthly_payment=Decimal("50000.00"))
    assert loan_balance(config, date(2024, 6, 1)) == Decimal(0)


def test_loan_to_value():
    assert loan_to_value(Decimal("80000"), Decimal("400000")) == Decimal("0.2")
    assert loan_to_value(Decimal("80000"), Decimal("0")) is None
