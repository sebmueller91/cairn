"""Mortgage amortization (spec 3.5): a full annuity schedule rather than
"outstanding balance, a number I update occasionally." A month-by-month
walk rather than the closed-form `K0*(1+i)^n - A*((1+i)^n-1)/i` directly,
because overpayments (EXTRA_REPAYMENT) change the balance path and the
closed form is only valid without them — recomputing an "effective
remaining term" after every overpayment is more code and more ways to get
it wrong than just walking forward a few hundred months, which is trivial
at this scale.
"""

import calendar
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
    # Bug fix (payment_day): which day-of-month the recurring schedule is
    # actually anchored on, matching `Loan.payment_day`. `None` (the
    # default) preserves the schedule's original, pre-fix behaviour of
    # anchoring on `start_date`'s own day-of-month — every existing
    # caller that doesn't wire this through yet keeps working exactly as
    # before.
    payment_day: int | None = None
    # Bug fix (fixed_until): `Loan.fixed_until` marks when a fixed-rate
    # period ends, but the spec never says what rate applies afterwards
    # (a variable rate tracked against some index? a renewal the human
    # negotiates and re-enters as a *new* loan? something else?).
    # Inventing an answer would be exactly the "invent domain rules"
    # AGENTS.md forbids, so this field is accepted here (wired through
    # from the model) purely so the limitation below is visible at the
    # call site, not silently dropped. `loan_balance` does NOT use it to
    # change the rate — see its docstring. This is a spec question for
    # the human, not a bug fix.
    fixed_until: date | None = None


def _add_one_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, d.day if d.day <= 31 else 31)
    year, month = d.year, d.month + 1
    # Clamp to the shortest month involved so e.g. Jan 31 -> Feb 28 rather
    # than raising — a payment schedule anchored on day 31 should still
    # walk forward every month, not just the long ones.
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def _subtract_one_month(d: date) -> date:
    if d.month == 1:
        year, month = d.year - 1, 12
    else:
        year, month = d.year, d.month - 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def _payment_anchor(start_date: date, payment_day: int) -> date:
    """The period-*start* reference date `_walk` should begin its walk
    from, so that the first scheduled payment lands on the first
    occurrence of `payment_day` strictly after `start_date` (bug fix:
    `Loan.payment_day` used to be stored but never read, so the
    schedule always anchored on `start_date`'s own day-of-month
    instead). `_walk` applies a step — and its payment — on the date
    `_add_one_month(current)` reaches, exactly mirroring how plain
    `start_date`-anchoring already works (first payment one month after
    `start_date`); this picks whichever `current` makes that arithmetic
    land on the right calendar day for `payment_day` instead:

    - If this month's `payment_day` falls strictly after `start_date`,
      that date *is* the first payment, one month out from `current`.
    - Otherwise (it's on/before `start_date` — including exactly on it,
      the plain-anchoring case) the first payment is next month's
      `payment_day` instead, one month out from *this* month's.

    Either way the result is "the payment date, minus one month",
    clamped the same way `_add_one_month` clamps day-31 to short
    months. When `payment_day` matches `start_date`'s own day-of-month
    this returns exactly `start_date` — the original, pre-fix anchor —
    so callers that never wire `payment_day` through are unaffected."""
    last_day = calendar.monthrange(start_date.year, start_date.month)[1]
    day = min(payment_day, last_day)
    candidate = date(start_date.year, start_date.month, day)
    first_payment = candidate if candidate > start_date else _add_one_month(candidate)
    return _subtract_one_month(first_payment)


def _walk(config: LoanConfig, as_of: date) -> tuple[Decimal, int]:
    """Shared step-by-step amortisation walk behind both `loan_balance`
    and `periods_elapsed`: applies one monthly compounding-then-payment
    step per payment-schedule anchor date, for every anchor on or before
    `as_of` (bug fix: previously `while current < as_of`, which applies
    one whole extra period — a full month's payment — before its anchor
    date has actually arrived, overstating every off-anniversary balance
    query by about one payment; the guard now matches `loan_balance`'s
    actual contract, "the balance as of this date", by only counting a
    period once its anchor date has been reached).  Returns
    `(balance, periods_applied)` so callers that need "how many payments
    happened in this window" (attribution_service.py's interest bucket)
    can reuse the exact same periodization `loan_balance` itself uses,
    rather than re-deriving it — including the early-payoff cutoff below."""
    monthly_rate = (config.annual_rate_pct / Decimal(100)) / Decimal(12)
    extra_by_month: dict[tuple[int, int], Decimal] = {}
    for d, amount in config.extra_repayments:
        key = (d.year, d.month)
        extra_by_month[key] = extra_by_month.get(key, Decimal(0)) + amount

    balance = config.principal
    periods = 0
    current = (
        _payment_anchor(config.start_date, config.payment_day)
        if config.payment_day is not None
        else config.start_date
    )
    while _add_one_month(current) <= as_of:
        # The extra repayment lookup uses *this* period's month (the one
        # about to elapse), not next month's — an overpayment dated
        # Jan 20 belongs to the January-to-February step, so it must be
        # keyed before `current` advances to February.
        period_key = (current.year, current.month)
        current = _add_one_month(current)
        balance = balance * (1 + monthly_rate) - config.monthly_payment
        periods += 1
        balance -= extra_by_month.get(period_key, Decimal(0))
        balance = max(balance, Decimal(0))
        if balance == 0:
            break
    return balance, periods


def loan_balance(config: LoanConfig, as_of: date) -> Decimal:
    """Outstanding balance as of `as_of`.

    Spec question (fixed_until — see `LoanConfig.fixed_until`'s
    docstring): this walk deliberately keeps compounding at
    `annual_rate_pct` for the loan's entire remaining life, including
    past `fixed_until`. There is no follow-on rate defined anywhere in
    the spec, and picking one (hold flat? track some index? require a
    human-entered renewal?) would be inventing a domain rule. So past a
    fixed-rate expiry this number is very likely wrong, and increasingly
    so the further past `fixed_until` you ask — that's a real
    limitation, not a silent one; flagged for the human to answer."""
    if as_of <= config.start_date:
        return config.principal
    balance, _ = _walk(config, as_of)
    return balance


def periods_elapsed(config: LoanConfig, start: date, end: date) -> int:
    """Number of monthly payment steps `loan_balance` actually applies
    within (start, end] — i.e. `loan_balance`'s own periodization,
    exposed for callers that need "how many regular payments were
    scheduled in this window" (attribution_service.py's interest
    bucket) without depending on optional LOAN_PAYMENT ledger rows,
    which per txn_service.py are record-keeping only and normally
    absent. Correctly stops counting once the loan has paid itself off
    within the window, since it reuses `_walk`'s own early-payoff cutoff
    on both sides of the subtraction below."""
    if end <= config.start_date:
        return 0
    _, periods_end = _walk(config, end)
    if start <= config.start_date:
        return periods_end
    _, periods_start = _walk(config, start)
    return periods_end - periods_start


def loan_to_value(loan_balance_eur: Decimal, house_value_eur: Decimal) -> Decimal | None:
    if house_value_eur <= 0:
        return None
    return loan_balance_eur / house_value_eur
