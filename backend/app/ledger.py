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
from decimal import Decimal
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


@dataclass
class Lot:
    quantity: Decimal
    unit_cost_eur: Decimal
    acquired_date: date


@dataclass
class Position:
    account_id: int
    instrument_id: int
    quantity: Decimal = Decimal(0)
    cost_basis_eur: Decimal = Decimal(0)
    realized_pl_eur: Decimal = Decimal(0)
    lots: list[Lot] = field(default_factory=list)


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
    total_cost = sum((lot.quantity * lot.unit_cost_eur for lot in queue), Decimal(0))
    total_qty = sum((lot.quantity for lot in queue), Decimal(0))
    for lot in queue:
        if total_cost != 0:
            share = (lot.quantity * lot.unit_cost_eur) / total_cost
        elif total_qty != 0:
            share = lot.quantity / total_qty
        else:
            return
        lot.unit_cost_eur += (amount_eur * share) / lot.quantity


def compute_positions(events: list[TxnEvent]) -> dict[tuple[int, int], Position]:
    """Replays events in (date, order) sequence and returns the resulting
    position per (account_id, instrument_id). Only events that actually
    move quantity or cost basis participate (BUY/SELL/TRANSFER/SPLIT/
    OPENING_BALANCE) — everything else (DIVIDEND, FEE, BALANCE_STATEMENT,
    ...) is a no-op here by design."""

    lots: dict[tuple[int, int], deque[Lot]] = {}
    realized_pl: dict[tuple[int, int], Decimal] = {}

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
                consumed.append(
                    Lot(
                        quantity=remaining,
                        unit_cost_eur=lot.unit_cost_eur,
                        acquired_date=lot.acquired_date,
                    )
                )
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
                    unit_cost_eur=event.amount_eur / event.quantity,
                    acquired_date=event.date,
                )
            )

        elif event.type == TransactionType.SELL:
            assert event.instrument_id is not None and event.quantity is not None
            consumed = _consume_fifo(
                event.account_id, event.instrument_id, event.quantity
            )
            cost_of_sold = sum(
                (lot.quantity * lot.unit_cost_eur for lot in consumed), Decimal(0)
            )
            key = (event.account_id, event.instrument_id)
            realized_pl[key] += event.amount_eur - cost_of_sold

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
                dest_queue.append(lot)

        elif event.type == TransactionType.SPLIT:
            assert event.instrument_id is not None and event.split_ratio is not None
            for key, queue in lots.items():
                if key[1] != event.instrument_id:
                    continue
                for lot in queue:
                    lot.quantity *= event.split_ratio
                    lot.unit_cost_eur /= event.split_ratio

    positions: dict[tuple[int, int], Position] = {}
    for key, queue in lots.items():
        account_id, instrument_id = key
        quantity = sum((lot.quantity for lot in queue), Decimal(0))
        cost_basis = sum(
            (lot.quantity * lot.unit_cost_eur for lot in queue), Decimal(0)
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
    return positions
