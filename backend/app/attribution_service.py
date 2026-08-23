"""Wealth attribution waterfall (spec 4.3): decomposes the change in gross
wealth over a period into named buckets that sum exactly to the observed
delta. `market_gains_losses` is deliberately the *residual* (delta_gross
minus every other bucket) rather than an independently computed "true"
market return — a fully separated day-by-day price/quantity/fx
decomposition is a much bigger undertaking, and a residual bucket is
standard practice in real attribution reports for exactly this reason.
It also absorbs a consequence of a limitation already documented in
performance_service.py: dividends and un-invested deposits currently have
zero effect on net worth in this schema until reinvested, so a period
with unreinvested dividend income or an uninvested deposit will show a
compensating shift in the residual that isn't really "the market" — an
honest byproduct of that gap, not a new one introduced here.

`deposits_withdrawals` covers the *whole* tracked-wealth perimeter (cash
accounts + BUY/SELL into MARKET positions) rather than raw DEPOSIT/
WITHDRAWAL transactions, for the same reason performance_service.py
scopes return-metric flows that way: an internal cash-account ->
brokerage transfer must net to zero here (nothing external happened),
which only works if both sides of that movement land in the same bucket.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.loan_service import LoanConfig, loan_balance, periods_elapsed
from app.models import (
    Account,
    AccountType,
    DailySnapshot,
    FxRate,
    Instrument,
    Loan,
    PricePoint,
    Txn,
    TransactionType,
    ValuationMode,
)
from app.valuation_service import current_instrument_value


@dataclass
class AttributionBuckets:
    start_date: date
    end_date: date
    start_value: Decimal
    end_value: Decimal
    deposits_withdrawals: Decimal
    income: Decimal
    costs: Decimal
    valuation_adjustments: Decimal
    fx_effect: Decimal
    market_gains_losses: Decimal


def _snapshot_value(db: Session, scope_type: str, scope_id: str, d: date) -> Decimal:
    row = (
        db.query(DailySnapshot)
        .filter(
            DailySnapshot.scope_type == scope_type,
            DailySnapshot.scope_id == scope_id,
            DailySnapshot.date == d,
        )
        .first()
    )
    return row.value_eur if row else Decimal(0)


def _cash_delta(db: Session, start: date, end: date) -> Decimal:
    accounts = db.query(Account).filter(Account.type == AccountType.CASH).all()
    return sum(
        (
            _snapshot_value(db, "cash_account", str(a.id), end)
            - _snapshot_value(db, "cash_account", str(a.id), start)
            for a in accounts
        ),
        Decimal(0),
    )


def _market_instrument_ids(db: Session) -> set[int]:
    return {
        row[0]
        for row in db.query(Instrument.id).filter(
            Instrument.valuation_mode == ValuationMode.MARKET
        )
    }


def _buy_sell_delta(db: Session, start: date, end: date) -> Decimal:
    market_ids = _market_instrument_ids(db)
    txns = (
        db.query(Txn)
        .filter(
            Txn.voided_at.is_(None),
            Txn.date > start,
            Txn.date <= end,
            Txn.type.in_([TransactionType.BUY, TransactionType.SELL]),
        )
        .all()
    )
    total = Decimal(0)
    for t in txns:
        if t.instrument_id not in market_ids:
            continue
        total += t.amount_eur if t.type == TransactionType.BUY else -t.amount_eur
    return total


def _sum_amounts(db: Session, types: list[TransactionType], start: date, end: date) -> Decimal:
    txns = (
        db.query(Txn)
        .filter(
            Txn.voided_at.is_(None), Txn.date > start, Txn.date <= end, Txn.type.in_(types)
        )
        .all()
    )
    return sum((t.amount_eur for t in txns), Decimal(0))


def _loan_interest(db: Session, start: date, end: date) -> Decimal:
    """Total interest paid across all loans in the period, backed out of
    each loan's already-tested amortization walk rather than parsed from
    a stored interest_part (deliberately not stored — see txn_service.py):
    interest = scheduled_payments - (balance_reduction attributable to
    those payments, i.e. total reduction minus extra repayments, which
    are 100% principal).

    Bug fix: `scheduled_payments` used to be summed from LOAN_PAYMENT
    ledger rows (`payments_paid`). But txn_service.py documents those as
    optional record-keeping — "the loan balance itself comes from
    loan_service's amortization model, not from summing these" — so the
    normal state is *zero* such rows, which made this read
    `0 - principal_reduction`, i.e. interest with the sign flipped
    (reported as a gain, not a cost) whenever no one bothers booking
    LOAN_PAYMENT transactions. Deriving the payment count from the same
    amortisation model `loan_balance` already uses (`periods_elapsed`)
    instead makes this correct whether or not LOAN_PAYMENT rows exist,
    matching the model's own contract rather than an optional ledger
    convention."""
    loans = db.query(Loan).all()
    total = Decimal(0)
    for loan in loans:
        extra_repayments = [
            (t.date, t.amount_eur)
            for t in db.query(Txn)
            .filter(
                Txn.account_id == loan.account_id,
                Txn.type == TransactionType.EXTRA_REPAYMENT,
                Txn.voided_at.is_(None),
            )
            .all()
        ]
        config = LoanConfig(
            principal=loan.principal,
            annual_rate_pct=loan.rate_pct,
            start_date=loan.start_date,
            monthly_payment=loan.monthly_payment,
            extra_repayments=extra_repayments,
            payment_day=loan.payment_day,
            fixed_until=loan.fixed_until,
        )
        balance_start = loan_balance(config, start)
        balance_end = loan_balance(config, end)
        extras_in_period = sum(
            (amt for d, amt in extra_repayments if start < d <= end), Decimal(0)
        )
        principal_reduction = (balance_start - balance_end) - extras_in_period
        scheduled_payments = config.monthly_payment * periods_elapsed(config, start, end)
        total += scheduled_payments - principal_reduction
    return total


def _valuation_adjustments(db: Session, start: date, end: date) -> Decimal:
    instruments = (
        db.query(Instrument)
        .filter(Instrument.valuation_mode.in_([ValuationMode.ANCHORED, ValuationMode.MODELED]))
        .all()
    )
    total = Decimal(0)
    for instrument in instruments:
        v_start = current_instrument_value(db, instrument.id, start) or Decimal(0)
        v_end = current_instrument_value(db, instrument.id, end) or Decimal(0)
        total += v_end - v_start
    return total


def _fx_effect(db: Session, start: date, end: date) -> Decimal:
    """First-order FX effect: for each foreign-currency MARKET instrument
    still held, the quantity and local-currency price held *at the start
    of the period* times the change in the EUR/local exchange rate. The
    smaller price-x-fx interaction term is left in the market_gains_losses
    residual, matching how most attribution reports treat it."""
    instruments = (
        db.query(Instrument)
        .filter(Instrument.valuation_mode == ValuationMode.MARKET, Instrument.currency != "EUR")
        .all()
    )
    total = Decimal(0)
    for instrument in instruments:
        rows = (
            db.query(DailySnapshot)
            .filter(DailySnapshot.scope_type == "position", DailySnapshot.date == start)
            .all()
        )
        qty_start = sum(
            (
                r.quantity
                for r in rows
                if r.scope_id.split(":")[1] == str(instrument.id) and r.quantity
            ),
            Decimal(0),
        )
        if qty_start == 0:
            continue
        price_start_row = (
            db.query(PricePoint)
            .filter(PricePoint.instrument_id == instrument.id, PricePoint.date <= start)
            .order_by(PricePoint.date.desc())
            .first()
        )
        fx_start_row = (
            db.query(FxRate)
            .filter(FxRate.currency == instrument.currency, FxRate.date <= start)
            .order_by(FxRate.date.desc())
            .first()
        )
        fx_end_row = (
            db.query(FxRate)
            .filter(FxRate.currency == instrument.currency, FxRate.date <= end)
            .order_by(FxRate.date.desc())
            .first()
        )
        if not (price_start_row and fx_start_row and fx_end_row):
            continue
        total += qty_start * price_start_row.close * (fx_end_row.eur_rate - fx_start_row.eur_rate)
    return total


def compute_attribution(db: Session, start: date, end: date) -> AttributionBuckets:
    # Spec question (NOT changed here — deliberately left as-is per
    # AGENTS.md "when the spec is ambiguous, say so and ask, do not
    # invent domain rules"): start/end_value use the `gross` scope,
    # which by construction excludes loans entirely (see
    # snapshot_service.py's module docstring — 'net' = 'gross' minus
    # loan balances), yet `costs` below subtracts loan interest, a
    # liability's own cost. Subtracting a cost belonging to something
    # `gross` never contained injects an equal phantom into the
    # `market_gains_losses` residual — every euro of loan interest shows
    # up twice: once correctly as a cost, once again as an unexplained
    # residual gain that cancels it back out, silently. Spec 4.3's "Δ
    # wealth including loan interest" reads like it wants the `net`
    # scope instead, but that's an interpretation, not something the
    # spec states outright — flagged for the human rather than switched
    # here.
    start_value = _snapshot_value(db, "total", "gross", start)
    end_value = _snapshot_value(db, "total", "gross", end)

    deposits_withdrawals = _cash_delta(db, start, end) + _buy_sell_delta(db, start, end)
    income = _sum_amounts(db, [TransactionType.DIVIDEND, TransactionType.INTEREST], start, end)
    costs = -(
        _sum_amounts(db, [TransactionType.FEE, TransactionType.TAX], start, end)
        + _loan_interest(db, start, end)
    )
    valuation_adjustments = _valuation_adjustments(db, start, end)
    fx_effect = _fx_effect(db, start, end)

    named_sum = deposits_withdrawals + income + costs + valuation_adjustments + fx_effect
    market_gains_losses = (end_value - start_value) - named_sum

    return AttributionBuckets(
        start_date=start,
        end_date=end,
        start_value=start_value,
        end_value=end_value,
        deposits_withdrawals=deposits_withdrawals,
        income=income,
        costs=costs,
        valuation_adjustments=valuation_adjustments,
        fx_effect=fx_effect,
        market_gains_losses=market_gains_losses,
    )


def month_end_boundaries(start: date, end: date) -> list[date]:
    """The measurement points for a monthly waterfall: `start` itself,
    then the last day of every month up to and including `end` (`end`
    itself if it isn't already a month-end). Consecutive pairs are the
    periods `compute_attribution` is called with."""
    boundaries = [start]
    d = date(start.year, start.month, 1)
    while True:
        next_month = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        month_end = next_month - timedelta(days=1)
        if month_end > start and month_end < end:
            boundaries.append(month_end)
        d = next_month
        if d > end:
            break
    if boundaries[-1] != end:
        boundaries.append(end)
    return boundaries


def year_end_boundaries(start: date, end: date) -> list[date]:
    boundaries = [start]
    for year in range(start.year, end.year + 1):
        year_end = date(year, 12, 31)
        if year_end > start and year_end < end:
            boundaries.append(year_end)
    if boundaries[-1] != end:
        boundaries.append(end)
    return boundaries


def attribution_series(
    db: Session, start: date, end: date, granularity: str
) -> list[AttributionBuckets]:
    if granularity == "month":
        boundaries = month_end_boundaries(start, end)
    elif granularity == "year":
        boundaries = year_end_boundaries(start, end)
    else:
        raise ValueError(f"unknown granularity: {granularity}")
    return [
        compute_attribution(db, b0, b1)
        for b0, b1 in zip(boundaries, boundaries[1:])
        if b0 < b1
    ]
