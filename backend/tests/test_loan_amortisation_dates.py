"""Reproductions for loan_service.py's off-anniversary amortisation bugs.
Hand-computed golden numbers, invented figures only (AGENTS.md).

Bug 2: `loan_balance` applied a whole period's payment a full month
early, because its loop guard (`while current < as_of`) let the walk
run one extra step before that step's anchor date had actually arrived.
The balance was only ever correct exactly on payment anniversaries --
which is exactly where the pre-existing test_loan_service.py happens to
query it, so this survived undetected. This file deliberately queries
off-anniversary dates.

Bug 3: `Loan.payment_day` was stored but never read, so the schedule
always anchored on `start_date`'s own day-of-month. `fixed_until` is
also stored but never read; the spec doesn't define a follow-on rate
past a fixed-rate expiry, so (per AGENTS.md's "do not invent domain
rules") this is answered by making the non-behaviour explicit and
documented rather than guessed -- see loan_service.py's docstrings.
"""

from datetime import date
from decimal import Decimal

from app.loan_service import LoanConfig, loan_balance, periods_elapsed


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


def test_balance_unchanged_between_anniversaries_not_one_month_early():
    """The exact reproduction from the bug report: pre-fix, this read
    99500.00 on all three of 2024-01-15, 2024-01-31 and 2024-02-01 --
    a full month's payment applied before the payment actually occurred.
    The balance must stay at the principal until the first anniversary
    is actually reached."""
    config = _config()
    assert loan_balance(config, date(2024, 1, 1)) == Decimal("100000.00")
    assert loan_balance(config, date(2024, 1, 15)) == Decimal("100000.00")
    assert loan_balance(config, date(2024, 1, 31)) == Decimal("100000.00")
    assert loan_balance(config, date(2024, 2, 1)) == Decimal("99500.00")
    # And it must stay there until the *next* anniversary, not drift
    # another month early again.
    assert loan_balance(config, date(2024, 2, 15)) == Decimal("99500.00")
    assert loan_balance(config, date(2024, 2, 29)) == Decimal("99500.00")
    assert loan_balance(config, date(2024, 3, 1)) == Decimal("98997.50")


def test_anniversary_balances_still_match_the_pre_existing_golden_numbers():
    """Sanity check that the loop-guard fix didn't change anything *on*
    the anniversaries themselves -- test_loan_service.py's existing
    golden numbers (which this file must not weaken or duplicate-own)
    still hold."""
    config = _config()
    assert loan_balance(config, date(2024, 2, 1)) == Decimal("99500.00")
    assert loan_balance(config, date(2024, 3, 1)) == Decimal("98997.50")


def test_payment_day_shifts_the_schedule_anchor_off_start_date():
    """A loan starting mid-month with payment_day=1 should have its
    first payment on the first of the *next* month, not one month after
    the 15th. Without payment_day wired through, the schedule silently
    anchors on start_date's own day-of-month (15) instead."""
    anchored_on_1st = _config(start_date=date(2024, 1, 15), payment_day=1)
    anchored_on_start_date = _config(start_date=date(2024, 1, 15))  # payment_day unset

    # Neither schedule has reached its first payment by Jan 31.
    assert loan_balance(anchored_on_1st, date(2024, 1, 31)) == Decimal("100000.00")
    assert loan_balance(anchored_on_start_date, date(2024, 1, 31)) == Decimal("100000.00")

    # payment_day=1 -> first payment lands Feb 1.
    assert loan_balance(anchored_on_1st, date(2024, 2, 1)) == Decimal("99500.00")
    # Unset payment_day -> still anchored on the 15th, so Feb 1 hasn't
    # reached the first anniversary (Feb 15) yet -- the two schedules
    # genuinely diverge, proving payment_day is actually being used.
    assert loan_balance(anchored_on_start_date, date(2024, 2, 1)) == Decimal("100000.00")
    assert loan_balance(anchored_on_start_date, date(2024, 2, 15)) == Decimal("99500.00")


def test_payment_day_default_matches_original_unwired_behaviour():
    """Backward compatibility: callers outside loan_service.py's
    ownership (routers/loans.py, snapshot_service.py) still construct
    LoanConfig without payment_day at all -- payment_day=None must
    reproduce the exact pre-fix anchor-on-start_date schedule so those
    call sites are unaffected by this change."""
    with_default_day = _config(start_date=date(2024, 1, 1))  # start_date.day == payment_day
    payment_day_matches_start = _config(start_date=date(2024, 1, 1), payment_day=1)
    for as_of in (date(2024, 1, 31), date(2024, 2, 1), date(2024, 3, 1)):
        assert loan_balance(with_default_day, as_of) == loan_balance(
            payment_day_matches_start, as_of
        )


def test_fixed_until_is_accepted_but_does_not_change_the_rate():
    """Spec question (see loan_service.py's LoanConfig.fixed_until and
    loan_balance docstrings): the spec never defines a follow-on rate
    past a fixed-rate expiry, so this deliberately does NOT invent one.
    fixed_until is wired through (accepted, doesn't crash, doesn't get
    silently dropped) but has zero effect on the computed balance --
    the walk keeps compounding at annual_rate_pct for the loan's entire
    life either way. That's the explicit, documented behaviour; it is
    very likely wrong for any real loan past its fixed period, which is
    exactly why this needs a human answer rather than a guess."""
    without_fixed_until = _config()
    with_fixed_until = _config(fixed_until=date(2024, 2, 1))  # expires after 1 period
    for as_of in (date(2024, 1, 15), date(2024, 2, 1), date(2024, 6, 1), date(2025, 1, 1)):
        assert loan_balance(with_fixed_until, as_of) == loan_balance(
            without_fixed_until, as_of
        )


def test_periods_elapsed_counts_regular_payment_steps_in_a_window():
    """Exposed for attribution_service.py's interest bucket (bug 4):
    counts how many monthly payment steps loan_balance() actually
    applies within (start, end], independent of any LOAN_PAYMENT ledger
    rows."""
    config = _config()
    assert periods_elapsed(config, date(2024, 1, 1), date(2024, 1, 31)) == 0
    assert periods_elapsed(config, date(2024, 1, 1), date(2024, 2, 1)) == 1
    assert periods_elapsed(config, date(2024, 1, 1), date(2024, 3, 1)) == 2
    # A window that starts after the loan's own inception still counts
    # correctly relative to its own start.
    assert periods_elapsed(config, date(2024, 2, 1), date(2024, 3, 1)) == 1


def test_periods_elapsed_stops_counting_once_the_loan_is_paid_off():
    config = _config(monthly_payment=Decimal("50000.00"))
    # Pays off well within 3 months; periods_elapsed must not keep
    # counting phantom payments past that, mirroring loan_balance's own
    # early-payoff cutoff.
    total_periods = periods_elapsed(config, date(2024, 1, 1), date(2025, 1, 1))
    assert total_periods == periods_elapsed(config, date(2024, 1, 1), date(2024, 6, 1))
