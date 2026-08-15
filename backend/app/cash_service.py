"""Cash valuation (spec 3.6): NOMINAL-mode CASH accounts are tracked by
balance only, via occasional BALANCE_STATEMENT entries, interpolated
between statements. The one subtlety that matters: a lump sum moving from
a cash account into a portfolio (a BUY draining the settlement balance
below zero, auto-booked as a DEPOSIT — see `derive_portfolio_deposits`)
must not also get smeared evenly across the interpolation period, or net
worth briefly double-counts that money — once still "in cash" by the
naive interpolation, once already inside the portfolio.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, AccountType, TransactionType, Txn

# Effect on a brokerage account's *internal* settlement balance, signed
# from the account's point of view. Types that don't move settlement cash
# (SPLIT, VALUATION, BALANCE_STATEMENT — that's for CASH accounts, not
# this) are simply absent and treated as zero effect.
_SETTLEMENT_EFFECT_SIGN = {
    TransactionType.BUY: -1,
    TransactionType.SELL: 1,
    TransactionType.DIVIDEND: 1,
    TransactionType.INTEREST: 1,
    TransactionType.FEE: -1,
    TransactionType.TAX: -1,
    TransactionType.DEPOSIT: 1,
    TransactionType.WITHDRAWAL: -1,
}


@dataclass
class DerivedDeposit:
    account_id: int
    date: date
    amount_eur: Decimal


def derive_portfolio_deposits(db: Session, account_id: int) -> list[DerivedDeposit]:
    """Walks one portfolio's securities transactions in order; whenever the
    running settlement balance would go negative, treats the shortfall as
    an external deposit on that date and resets to zero. A dividend
    funding the next purchase never creates a deposit (spec 3.6)."""
    txns = (
        db.query(Txn)
        .filter(Txn.account_id == account_id, Txn.voided_at.is_(None))
        .order_by(Txn.date, Txn.id)
        .all()
    )
    balance = Decimal(0)
    deposits: list[DerivedDeposit] = []
    for txn in txns:
        sign = _SETTLEMENT_EFFECT_SIGN.get(txn.type)
        if sign is None:
            continue
        balance += sign * txn.amount_eur
        if balance < 0:
            shortfall = -balance
            deposits.append(DerivedDeposit(account_id, txn.date, shortfall))
            balance = Decimal(0)
    return deposits


def all_known_deposits(db: Session) -> list[DerivedDeposit]:
    portfolio_accounts = (
        db.query(Account)
        .filter(Account.type.in_([AccountType.BROKERAGE, AccountType.CRYPTO_WALLET]))
        .all()
    )
    deposits: list[DerivedDeposit] = []
    for account in portfolio_accounts:
        deposits.extend(derive_portfolio_deposits(db, account.id))
    return deposits


def interpolate_cash_balance(
    statements: list[tuple[date, Decimal]],
    known_deposits: list[Decimal | tuple[date, Decimal]],
) -> dict[date, Decimal]:
    """Daily balance for every day spanned by consecutive BALANCE_STATEMENT
    entries. `known_deposits` are (date, amount) pairs of money that left
    this cash account for a portfolio, already reflected in the *next*
    statement's balance — subtracted out before spreading the remaining,
    genuinely unexplained change linearly across the period."""
    result: dict[date, Decimal] = {}
    if not statements:
        return result

    ordered = sorted(statements, key=lambda s: s[0])
    result[ordered[0][0]] = ordered[0][1]

    for (d1, b1), (d2, b2) in zip(ordered, ordered[1:]):
        deposits_in_range = sorted(
            (amt_date, amt) for amt_date, amt in known_deposits if d1 < amt_date <= d2
        )
        explained = sum((amt for _, amt in deposits_in_range), Decimal(0))
        total_days = (d2 - d1).days
        if total_days <= 0:
            result[d2] = b2
            continue
        residual_delta = (b2 - b1) + explained
        per_day = residual_delta / total_days

        running = b1
        for offset in range(1, total_days + 1):
            day = d1 + timedelta(days=offset)
            running += per_day
            for amt_date, amt in deposits_in_range:
                if amt_date == day:
                    running -= amt
            result[day] = running
        # Anchor exactly on the statement's own reported figure rather
        # than whatever rounding drift accumulated — the statement is
        # ground truth, the interpolation is only for the days between.
        result[d2] = b2

    return result
