"""Return metrics (spec 4.2): TWR (time-weighted) and MWR/XIRR (money-weighted).

Scope: the *investable portfolio's priced positions* only (BUY/SELL-tracked
instrument holdings with `valuation_mode=MARKET`) — not raw CASH-account
balances, and not house/car. Two reasons: (1) spec 4.1 frames "return" as
answering "how good were my investments," and decision #5 explicitly calls
a cash account's balance change "savings rate," a different metric, not
investment return; (2) mechanically, this app's ledger never tracks a
brokerage account's uninvested settlement cash as a valued quantity at all
(a bare DEPOSIT has zero effect on any position's value until it funds a
BUY) — so folding cash accounts into V would require inventing a
settlement-cash valuation this schema doesn't have, while excluding them
keeps V exactly equal to the sum of `daily_snapshot` position rows for
MARKET instruments, which the snapshot engine already computes and is
proven correct (rebuild_snapshots).

Flow definition, given V only ever moves for two reasons in this schema —
market price/quantity revaluation, or a BUY/SELL/TRANSFER changing which
lots exist: a BUY conjures a new lot valued at its cost that day (money
entering V's universe from untracked settlement cash — a flow, not
return); a SELL removes a lot's value (a flow leaving V's universe to
become untracked settlement cash). Both are already recorded at their
market-equivalent amount (`amount_eur` = quantity x price +/- fees/tax),
so no separate valuation lookup is needed for them. TRANSFER moves a lot
between two of the household's own accounts/instruments at zero net
effect on the *total* scope (quantity leaves one bucket, arrives in
another, aggregate V unchanged) but is a genuine flow relative to a
*single* account or instrument scope — valued at the current market price
on the transfer date, since TRANSFER's own stored `amount_eur` is ~zero
(ledger.py moves lots at cost basis, not market value).

DIVIDEND/INTEREST/FEE/TAX never touch V either way (none are quantity-
bearing in ledger.py) — for this position-value-only scope they are
simply invisible, same as they already are to the FIFO cost-basis ledger
itself. This is a real limitation worth naming, not silently working
around: this app currently has no model at all for uninvested brokerage
cash or un-reinvested dividend cash contributing to net worth. Fixing
that is a snapshot-engine change (touching phases 1-5's already-shipped,
tested valuation model), out of scope for a return-metrics feature —
flagged here for whoever revisits it.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

_DAY_COUNT = Decimal(365)


@dataclass
class FlowEvent:
    date: date
    amount: Decimal  # positive = money entering the scope, negative = leaving


def _flows_by_date(flows: list[FlowEvent]) -> dict[date, Decimal]:
    by_date: dict[date, Decimal] = {}
    for f in flows:
        by_date[f.date] = by_date.get(f.date, Decimal(0)) + f.amount
    return by_date


def daily_returns(
    values: list[tuple[date, Decimal]], flows: list[FlowEvent]
) -> list[tuple[date, Decimal]]:
    """One chained sub-period return per consecutive day pair:
    r(t) = (V(t) - flow(t) - V(t-1)) / V(t-1). `values` must be sorted and
    dense (one entry per calendar day, no gaps) over the range. A day
    whose starting value is zero (nothing invested yet) is skipped — a
    return needs a nonzero prior base to be relative to."""
    out: list[tuple[date, Decimal]] = []
    if len(values) < 2:
        return out
    flow_map = _flows_by_date(flows)
    for (d0, v0), (d1, v1) in zip(values, values[1:]):
        if v0 == 0:
            continue
        flow = flow_map.get(d1, Decimal(0))
        r = (v1 - flow - v0) / v0
        out.append((d1, r))
    return out


def chain_link(returns: list[tuple[date, Decimal]]) -> Decimal:
    """Total TWR across a series of daily returns: product(1+r) - 1."""
    growth = Decimal(1)
    for _, r in returns:
        growth *= Decimal(1) + r
    return growth - Decimal(1)


def cumulative_index(
    returns: list[tuple[date, Decimal]], base: Decimal = Decimal(100)
) -> list[tuple[date, Decimal]]:
    """A chart-ready growth-of-`base` curve, one point per return."""
    out: list[tuple[date, Decimal]] = []
    level = base
    for d, r in returns:
        level *= Decimal(1) + r
        out.append((d, level))
    return out


def twr(values: list[tuple[date, Decimal]], flows: list[FlowEvent]) -> Decimal:
    return chain_link(daily_returns(values, flows))


def shadow_value_series(
    dates: list[date],
    flows: list[FlowEvent],
    benchmark_price: dict[date, Decimal],
) -> list[tuple[date, Decimal]]:
    """"What if every contribution had gone into this benchmark instead"
    (spec 4.2): each flow buys (or sells) fictional benchmark units at
    that day's price, mirroring the real portfolio's own flow schedule
    exactly so the two are genuinely comparable. `benchmark_price` must
    already be carry-forward resolved (one entry per date in `dates`,
    or missing where truly unpriced). The result is a plain value
    series — feed it through `daily_returns`/`cumulative_index` the same
    way as the real portfolio's V(t) for a directly overlayable curve."""
    flow_map = _flows_by_date(flows)
    units = Decimal(0)
    out: list[tuple[date, Decimal]] = []
    for d in dates:
        price = benchmark_price.get(d)
        flow = flow_map.get(d)
        if flow and price:
            units += flow / price
        value = units * price if price is not None else Decimal(0)
        out.append((d, value))
    return out


def _xirr_npv(cashflows: list[tuple[date, Decimal]], rate: float, d0: date) -> float:
    return sum(
        float(amt) / (1.0 + rate) ** (float((d - d0).days) / float(_DAY_COUNT))
        for d, amt in cashflows
    )


def _xirr_dnpv(cashflows: list[tuple[date, Decimal]], rate: float, d0: date) -> float:
    return sum(
        -float(amt)
        * (float((d - d0).days) / float(_DAY_COUNT))
        / (1.0 + rate) ** (float((d - d0).days) / float(_DAY_COUNT) + 1.0)
        for d, amt in cashflows
    )


def xirr(
    cashflows: list[tuple[date, Decimal]], guess: float = 0.1
) -> float | None:
    """Money-weighted return (spec 4.2's MWR/XIRR) via Newton-Raphson with
    a bisection fallback. `cashflows` needs at least one negative
    (outflow/investment) and one positive (inflow/current value) entry.
    Returns an annualised rate as a float — this is a read-time derived
    metric, not stored money, so float is the right tool (no exact-Decimal
    rule applies; that rule is about the ledger, ADR/AGENTS.md)."""
    if len(cashflows) < 2:
        return None
    amounts = [amt for _, amt in cashflows]
    if not any(a < 0 for a in amounts) or not any(a > 0 for a in amounts):
        return None
    d0 = min(d for d, _ in cashflows)

    rate = guess
    for _ in range(100):
        f = _xirr_npv(cashflows, rate, d0)
        fprime = _xirr_dnpv(cashflows, rate, d0)
        if fprime == 0:
            break
        step = f / fprime
        new_rate = rate - step
        if new_rate <= -1.0:
            new_rate = (rate - 1.0) / 2.0  # keep 1+rate positive
        if abs(new_rate - rate) < 1e-9:
            return new_rate
        rate = new_rate

    # Newton didn't converge (pathological cash-flow pattern) — bisection
    # over a wide bracket is slower but always converges if a root exists
    # in range.
    lo, hi = -0.999999, 10.0
    f_lo = _xirr_npv(cashflows, lo, d0)
    f_hi = _xirr_npv(cashflows, hi, d0)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = _xirr_npv(cashflows, mid, d0)
        if abs(f_mid) < 1e-6:
            return mid
        if (f_lo < 0) == (f_mid < 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def mwr(
    start_date: date,
    start_value: Decimal,
    flows: list[FlowEvent],
    end_date: date,
    end_value: Decimal,
) -> float | None:
    """XIRR over a period: the starting value is an implicit outflow (money
    "invested" at the start of the window), each flow in between keeps its
    own sign, and the ending value is an implicit inflow (what it's worth
    now). Same reasoning as `twr` for what counts as a flow."""
    cashflows: list[tuple[date, Decimal]] = []
    if start_value != 0:
        cashflows.append((start_date, -start_value))
    for f in flows:
        # A FlowEvent's amount is signed from the *scope's* point of view
        # (positive = money entering it, e.g. a BUY). XIRR wants the
        # investor's point of view instead (negative = money leaving their
        # pocket to fund it) — exactly the opposite sign.
        cashflows.append((f.date, -f.amount))
    cashflows.append((end_date, end_value))
    return xirr(cashflows)
