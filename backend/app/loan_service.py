"""Mortgage amortization (spec 3.5): a full annuity schedule rather than
"outstanding balance, a number I update occasionally." A month-by-month
walk rather than the closed-form `K0*(1+i)^n - A*((1+i)^n-1)/i` directly,
because overpayments (EXTRA_REPAYMENT) change the balance path and the
closed form is only valid without them — recomputing an "effective
remaining term" after every overpayment is more code and more ways to get
it wrong than just walking forward a few hundred months, which is trivial
at this scale.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class LoanConfig:
    principal: Decimal
    annual_rate_pct: Decimal
    start_date: date
    monthly_payment: Decimal
    extra_repayments: list[tuple[date, Decimal]] = field(default_factory=list)


def _add_one_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, d.day if d.day <= 31 else 31)
    year, month = d.year, d.month + 1
    # Clamp to the shortest month involved so e.g. Jan 31 -> Feb 28 rather
    # than raising — a payment schedule anchored on day 31 should still
    # walk forward every month, not just the long ones.
    import calendar

    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def loan_balance(config: LoanConfig, as_of: date) -> Decimal:
    if as_of <= config.start_date:
        return config.principal

    monthly_rate = (config.annual_rate_pct / Decimal(100)) / Decimal(12)
    extra_by_month: dict[tuple[int, int], Decimal] = {}
    for d, amount in config.extra_repayments:
        key = (d.year, d.month)
        extra_by_month[key] = extra_by_month.get(key, Decimal(0)) + amount

    balance = config.principal
    current = config.start_date
    while current < as_of:
        # The extra repayment lookup uses *this* period's month (the one
        # about to elapse), not next month's — an overpayment dated
        # Jan 20 belongs to the January-to-February step, so it must be
        # keyed before `current` advances to February.
        period_key = (current.year, current.month)
        current = _add_one_month(current)
        balance = balance * (1 + monthly_rate) - config.monthly_payment
        balance -= extra_by_month.get(period_key, Decimal(0))
        balance = max(balance, Decimal(0))
        if balance == 0:
            break
    return balance


def loan_to_value(loan_balance_eur: Decimal, house_value_eur: Decimal) -> Decimal | None:
    if house_value_eur <= 0:
        return None
    return loan_balance_eur / house_value_eur
