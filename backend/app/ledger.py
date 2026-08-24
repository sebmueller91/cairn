"""Holdings and FIFO cost-basis computation.

Pure functions over plain data (no ORM, no DB session) so the core ledger
math is testable in isolation — this is the "number I need to trust before
anything else" per AGENTS.md, hence test-first.

Positions are never stored (ADR 0003): this module is the single place that
turns a transaction history into a quantity + cost basis, on demand.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from app.models import TransactionType

if TYPE_CHECKING:
    from app.models import Txn


class InsufficientHoldingError(ValueError):
    def __init__(
        self,
        account_id: int,
        instrument_id: int,
        requested: Decimal,
        available: Decimal,
    ):
        self.account_id = account_id
        self.instrument_id = instrument_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"account {account_id} / instrument {instrument_id}: "
            f"requested {requested}, only {available} held"
        )


@dataclass
class TxnEvent:
    """The subset of a txn row this module needs. `order` breaks ties for
    same-day events deterministically (pass the txn id)."""

    order: int
    type: TransactionType
    date: date
    account_id: int
    instrument_id: int | None
    counter_account_id: int | None
    quantity: Decimal | None
    amount_eur: Decimal
    split_ratio: Decimal | None = None


# Matches db_types.Quantity.MAX_DECIMAL_PLACES (8dp, BTC precision) — the
# DailySnapshot.quantity column this feeds cannot hold more, so a lot's
# quantity is quantized here rather than letting a full-precision SPLIT
# multiplication reach the DB boundary and raise there instead.
_QUANTITY_QUANTUM = Decimal("0.00000001")


def add_years(start: date, years: int) -> date:
    """`start` shifted by whole calendar years, clamping 29 February to
    28 February in a non-leap target year. Written out rather than
    pulled from dateutil — one call site, no new dependency."""
    try:
        return start.replace(year=start.year + years)
    except ValueError:
        return start.replace(year=start.year + years, month=2, day=28)


def holding_period_elapsed(
    acquired: date, disposed: date, years: int
) -> bool:
    """True when `disposed` falls after the speculation period expired.

    German §23 EStG counts the period between acquisition and sale and
    requires it to *exceed* the term, so a sale exactly one year to the
    day after purchase is still taxable — hence the strict `>`. Day
    counting (`>= 365`) is deliberately not used: it disagrees with the
    statute across leap years."""
    return disposed > add_years(acquired, years)


@dataclass
class Lot:
    quantity: Decimal
    # The lot's total cost, carried exactly through BUY/SPLIT/adjustments —
    # never derived by multiplying a stored per-unit cost back out. A split
    # with a ratio that doesn't divide evenly in base 10 (3, 7, ...) has no
    # finite per-unit cost that reconstructs the original total exactly, so
    # anything computed by repeatedly dividing and re-multiplying drifts by
    # a tiny but real amount. Tracking the total directly avoids that: a
    # SPLIT changes quantity, never total_cost_eur (bug: split cost basis
    # drift).
    total_cost_eur: Decimal
    acquired_date: date

    @property
    def unit_cost_eur(self) -> Decimal:
        """Derived display/consumption convenience only — nothing in this
        module reconstructs a total from this value."""
        if self.quantity == 0:
            return Decimal(0)
        return self.total_cost_eur / self.quantity


@dataclass
class Position:
    account_id: int
    instrument_id: int
    quantity: Decimal = Decimal(0)
    cost_basis_eur: Decimal = Decimal(0)
    realized_pl_eur: Decimal = Decimal(0)
    lots: list[Lot] = field(default_factory=list)


@dataclass
class RealizedSale:
    """One SELL, with the FIFO lots it actually consumed.

    `realized_pl_eur` on Position is a lifetime total per (account,
    instrument) and cannot answer "which gains fell in 2025" or "how
    much of this gain came from lots held over a year" — both of which
    the German tax view needs (§20 saver's allowance is per calendar
    year, §23 exempts anything held longer than the speculation
    period). Emitting the individual sales here is what let
    tax_service drop its own second FIFO replay of the same ledger.

    `consumed_lots` are fragments owned by this record — `_consume_fifo`
    either hands over a lot it removed from the queue or builds a fresh
    partial one, so nothing here aliases a lot still being mutated.
    """

    date: date
    order: int
    account_id: int
    instrument_id: int
    quantity: Decimal
    proceeds_eur: Decimal
    cost_basis_eur: Decimal
    consumed_lots: list[Lot] = field(default_factory=list)

    @property
    def gain_eur(self) -> Decimal:
        return self.proceeds_eur - self.cost_basis_eur

    def gain_split_by_holding_period(
        self, holding_period_years: int
    ) -> tuple[Decimal, Decimal]:
        """Splits this sale's gain into (long_held, short_held) by
        apportioning proceeds across the consumed lots by quantity.

        A sale's proceeds arrive as one figure for the whole quantity;
        there is no per-lot sale price to use, so quantity is the only
        defensible key. Cost is taken from each lot directly rather than
        apportioned, so the two parts always sum back to gain_eur
        exactly (the last lot absorbs any division remainder).
        """
        total_qty = sum((lot.quantity for lot in self.consumed_lots), Decimal(0))
        if total_qty == 0:
            return Decimal(0), Decimal(0)
        long_held = Decimal(0)
        short_held = Decimal(0)
        assigned_proceeds = Decimal(0)
        for index, lot in enumerate(self.consumed_lots):
            if index == len(self.consumed_lots) - 1:
                share = self.proceeds_eur - assigned_proceeds
            else:
                share = self.proceeds_eur * lot.quantity / total_qty
                assigned_proceeds += share
            gain = share - lot.total_cost_eur
            if holding_period_elapsed(
                lot.acquired_date, self.date, holding_period_years
            ):
                long_held += gain
            else:
                short_held += gain
        return long_held, short_held


@dataclass
class LedgerResult:
    positions: dict[tuple[int, int], Position]
    sales: list[RealizedSale]


def txn_to_event(txn: "Txn") -> TxnEvent:
    """Shared conversion used everywhere a stored transaction needs to
    become ledger input — the fetch/write/supersede/snapshot code paths
    all replay history through this same module and should agree on
    exactly what a Txn row means as an event."""
    return TxnEvent(
        order=txn.id,
        type=txn.type,
        date=txn.date,
        account_id=txn.account_id,
        instrument_id=txn.instrument_id,
        counter_account_id=txn.counter_account_id,
        quantity=txn.quantity,
        amount_eur=txn.amount_eur,
        split_ratio=txn.split_ratio,
    )


_QUANTITY_BEARING_TYPES = {
    TransactionType.BUY,
    TransactionType.SELL,
    TransactionType.TRANSFER,
    TransactionType.SPLIT,
    TransactionType.OPENING_BALANCE,
}


def _insert_by_acquired_date(queue: "deque[Lot]", lot: Lot) -> None:
    """Inserts `lot` into `queue` keeping it ordered by acquired_date so
    FIFO consumption follows acquisition date rather than arrival order.
    Stable: a lot lands after every existing lot with an equal-or-earlier
    date, so ties keep the order they already had in the queue."""
    index = len(queue)
    for i, existing in enumerate(queue):
        if existing.acquired_date > lot.acquired_date:
            index = i
            break
    queue.insert(index, lot)


def _adjust_cost_basis(queue: "deque[Lot]", amount_eur: Decimal) -> None:
    """Spreads a cost-only correction across the lots currently held.

    Proportional to each lot's cost so the split is stable under later
    FIFO consumption; by quantity when the lots carry no cost at all
    (a fully written-down holding), and dropped entirely when there is
    nothing on hand — there is no position left for the correction to
    attach to, and inventing a lot with no shares would corrupt FIFO.
    """
    if not queue or amount_eur == 0:
        return
    total_cost = sum((lot.total_cost_eur for lot in queue), Decimal(0))
    total_qty = sum((lot.quantity for lot in queue), Decimal(0))
    for lot in queue:
        if total_cost != 0:
            share = lot.total_cost_eur / total_cost
        elif total_qty != 0:
            share = lot.quantity / total_qty
        else:
            return
        lot.total_cost_eur += amount_eur * share


def replay(events: list[TxnEvent]) -> LedgerResult:
    """Replays events in (date, order) sequence and returns the resulting
    position per (account_id, instrument_id) plus the individual sales
    that happened along the way. Only events that actually move quantity
    or cost basis participate (BUY/SELL/TRANSFER/SPLIT/OPENING_BALANCE)
    — everything else (DIVIDEND, FEE, BALANCE_STATEMENT, ...) is a no-op
    here by design.

    Most callers only want the positions and should keep using
    compute_positions(); the sales log exists for the tax view, which
    needs gains broken out by date and holding period."""

    lots: dict[tuple[int, int], deque[Lot]] = {}
    realized_pl: dict[tuple[int, int], Decimal] = {}
    sales: list[RealizedSale] = []

    def _queue(account_id: int, instrument_id: int) -> deque[Lot]:
        key = (account_id, instrument_id)
        if key not in lots:
            lots[key] = deque()
            realized_pl[key] = Decimal(0)
        return lots[key]

    def _consume_fifo(
        account_id: int, instrument_id: int, quantity: Decimal
    ) -> list[Lot]:
        """Removes `quantity` from the front of the FIFO queue, returning
        the exact lot fragments consumed (for cost-basis calculations or
        to recreate them elsewhere, as TRANSFER does)."""
        queue = _queue(account_id, instrument_id)
        available = sum((lot.quantity for lot in queue), Decimal(0))
        if quantity > available:
            raise InsufficientHoldingError(
                account_id, instrument_id, quantity, available
            )
        consumed: list[Lot] = []
        remaining = quantity
        while remaining > 0:
            lot = queue[0]
            if lot.quantity <= remaining:
                consumed.append(lot)
                remaining -= lot.quantity
                queue.popleft()
            else:
                fragment_cost = remaining * lot.unit_cost_eur
                consumed.append(
                    Lot(
                        quantity=remaining,
                        total_cost_eur=fragment_cost,
                        acquired_date=lot.acquired_date,
                    )
                )
                # Subtracting (rather than independently recomputing the
                # remainder's own total) guarantees fragment + remainder
                # sum back to the lot's original total exactly, regardless
                # of whether unit_cost_eur itself divided evenly.
                lot.total_cost_eur -= fragment_cost
                lot.quantity -= remaining
                remaining = Decimal(0)
        return consumed

    for event in sorted(events, key=lambda e: (e.date, e.order)):
        if event.type not in _QUANTITY_BEARING_TYPES:
            continue

        if event.type in (TransactionType.BUY, TransactionType.OPENING_BALANCE):
            assert event.instrument_id is not None and event.quantity is not None
            queue = _queue(event.account_id, event.instrument_id)
            if event.quantity == 0:
                # A zero-quantity entry is a pure cost-basis correction, not
                # a lot: supersede emits exactly this when a backfill explains
                # every share but not the full cost basis. There is no unit
                # cost to divide out, so spread the amount over the lots on
                # hand instead — proportionally to their cost where there is
                # any, otherwise by quantity.
                _adjust_cost_basis(queue, event.amount_eur)
                continue
            queue.append(
                Lot(
                    quantity=event.quantity,
                    total_cost_eur=event.amount_eur,
                    acquired_date=event.date,
                )
            )

        elif event.type == TransactionType.SELL:
            assert event.instrument_id is not None and event.quantity is not None
            consumed = _consume_fifo(
                event.account_id, event.instrument_id, event.quantity
            )
            cost_of_sold = sum((lot.total_cost_eur for lot in consumed), Decimal(0))
            key = (event.account_id, event.instrument_id)
            realized_pl[key] += event.amount_eur - cost_of_sold
            sales.append(
                RealizedSale(
                    date=event.date,
                    order=event.order,
                    account_id=event.account_id,
                    instrument_id=event.instrument_id,
                    quantity=event.quantity,
                    proceeds_eur=event.amount_eur,
                    cost_basis_eur=cost_of_sold,
                    consumed_lots=consumed,
                )
            )

        elif event.type == TransactionType.TRANSFER:
            assert (
                event.instrument_id is not None
                and event.quantity is not None
                and event.counter_account_id is not None
            )
            consumed = _consume_fifo(
                event.account_id, event.instrument_id, event.quantity
            )
            dest_queue = _queue(event.counter_account_id, event.instrument_id)
            for lot in consumed:
                # Insert by acquired_date (stable for ties) rather than
                # appending — a transfer must not let its own arrival order
                # jump the destination's existing FIFO queue ahead of an
                # older lot that happens to arrive later.
                _insert_by_acquired_date(dest_queue, lot)

        elif event.type == TransactionType.SPLIT:
            assert event.instrument_id is not None and event.split_ratio is not None
            for key, queue in lots.items():
                if key[1] != event.instrument_id:
                    continue
                for lot in queue:
                    # total_cost_eur is left untouched: a split changes
                    # quantity and (derived) unit cost, never the total.
                    # Only quantize when the multiplication actually
                    # overflows what the DailySnapshot column can store
                    # (8dp) — an exact result (e.g. an integer ratio
                    # applied to a whole-share quantity) is left with its
                    # natural precision instead of being padded with
                    # trailing zeros it never had.
                    new_quantity = lot.quantity * event.split_ratio
                    exponent = new_quantity.as_tuple().exponent
                    if isinstance(exponent, int) and exponent < -8:
                        new_quantity = new_quantity.quantize(
                            _QUANTITY_QUANTUM, rounding=ROUND_HALF_UP
                        )
                    lot.quantity = new_quantity

    positions: dict[tuple[int, int], Position] = {}
    for key, queue in lots.items():
        account_id, instrument_id = key
        quantity = sum((lot.quantity for lot in queue), Decimal(0))
        cost_basis = sum(
            (lot.total_cost_eur for lot in queue), Decimal(0)
        )
        if quantity == 0 and realized_pl[key] == 0:
            continue
        positions[key] = Position(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=quantity,
            cost_basis_eur=cost_basis,
            realized_pl_eur=realized_pl[key],
            lots=list(queue),
        )
    return LedgerResult(positions=positions, sales=sales)


def compute_positions(events: list[TxnEvent]) -> dict[tuple[int, int], Position]:
    """Positions only — the shape every caller outside the tax view
    expects. See replay() for the full result."""
    return replay(events).positions
