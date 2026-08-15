"""Golden-dataset-style tests for app.ledger — the core position and
FIFO cost-basis math. Invented instrument/account ids and numbers only.

FX purchases and native-currency pricing are a write-time concern (fx_rate
applied to derive amount_eur, tested at the API layer once it exists) —
app.ledger only ever sees already-converted EUR amounts, so there's no
FX-specific behaviour to test here.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.ledger import InsufficientHoldingError, TxnEvent, compute_positions
from app.models import TransactionType

ACCOUNT_A = 1
ACCOUNT_B = 2
INSTRUMENT_X = 100


def _buy(order, d, qty, amount_eur, account=ACCOUNT_A, instrument=INSTRUMENT_X):
    return TxnEvent(
        order=order,
        type=TransactionType.BUY,
        date=d,
        account_id=account,
        instrument_id=instrument,
        counter_account_id=None,
        quantity=Decimal(qty),
        amount_eur=Decimal(amount_eur),
    )


def test_single_buy_establishes_position():
    events = [_buy(1, date(2024, 1, 10), "10", "1000.00")]
    positions = compute_positions(events)
    pos = positions[(ACCOUNT_A, INSTRUMENT_X)]
    assert pos.quantity == Decimal("10")
    assert pos.cost_basis_eur == Decimal("1000.00")
    assert pos.realized_pl_eur == Decimal(0)


def test_partial_sale_uses_fifo_cost_basis():
    events = [
        _buy(1, date(2024, 1, 10), "10", "1000.00"),  # unit cost 100
        _buy(2, date(2024, 3, 1), "10", "1200.00"),  # unit cost 120
        TxnEvent(
            order=3,
            type=TransactionType.SELL,
            date=date(2024, 6, 1),
            account_id=ACCOUNT_A,
            instrument_id=INSTRUMENT_X,
            counter_account_id=None,
            quantity=Decimal("12"),
            amount_eur=Decimal("1500.00"),  # net proceeds
        ),
    ]
    positions = compute_positions(events)
    pos = positions[(ACCOUNT_A, INSTRUMENT_X)]
    # FIFO: sells all 10 units from the first lot (cost 1000) + 2 units
    # from the second lot (cost 2 * 120 = 240) -> cost of sold = 1240
    assert pos.quantity == Decimal("8")
    assert pos.cost_basis_eur == Decimal("960.00")  # 8 remaining units * 120
    assert pos.realized_pl_eur == Decimal("1500.00") - Decimal("1240.00")


def test_overselling_raises():
    events = [
        _buy(1, date(2024, 1, 10), "10", "1000.00"),
        TxnEvent(
            order=2,
            type=TransactionType.SELL,
            date=date(2024, 2, 1),
            account_id=ACCOUNT_A,
            instrument_id=INSTRUMENT_X,
            counter_account_id=None,
            quantity=Decimal("11"),
            amount_eur=Decimal("1100.00"),
        ),
    ]
    with pytest.raises(InsufficientHoldingError):
        compute_positions(events)


def test_split_applies_retroactively_to_existing_lots_only():
    events = [
        _buy(1, date(2024, 1, 10), "10", "1000.00"),  # pre-split, unit cost 100
        TxnEvent(
            order=2,
            type=TransactionType.SPLIT,
            date=date(2024, 3, 1),
            account_id=ACCOUNT_A,
            instrument_id=INSTRUMENT_X,
            counter_account_id=None,
            quantity=None,
            amount_eur=Decimal(0),
            split_ratio=Decimal(2),
        ),
        _buy(3, date(2024, 4, 1), "5", "500.00"),  # post-split, unaffected
    ]
    positions = compute_positions(events)
    pos = positions[(ACCOUNT_A, INSTRUMENT_X)]
    # pre-split lot: 10 -> 20 units at unit cost 50; post-split buy: 5 units at 100
    assert pos.quantity == Decimal("25")
    assert pos.cost_basis_eur == Decimal("1500.00")  # value is conserved by the split


def test_dividend_has_no_quantity_or_cost_basis_effect():
    events = [
        _buy(1, date(2024, 1, 10), "10", "1000.00"),
        TxnEvent(
            order=2,
            type=TransactionType.DIVIDEND,
            date=date(2024, 6, 1),
            account_id=ACCOUNT_A,
            instrument_id=INSTRUMENT_X,
            counter_account_id=None,
            quantity=None,
            amount_eur=Decimal("15.00"),
        ),
    ]
    positions = compute_positions(events)
    pos = positions[(ACCOUNT_A, INSTRUMENT_X)]
    assert pos.quantity == Decimal("10")
    assert pos.cost_basis_eur == Decimal("1000.00")


def test_transfer_moves_lots_with_cost_basis_intact():
    events = [
        _buy(1, date(2024, 1, 10), "10", "1000.00"),
        TxnEvent(
            order=2,
            type=TransactionType.TRANSFER,
            date=date(2024, 5, 1),
            account_id=ACCOUNT_A,
            instrument_id=INSTRUMENT_X,
            counter_account_id=ACCOUNT_B,
            quantity=Decimal("4"),
            amount_eur=Decimal(0),  # no cash effect, in-kind transfer
        ),
    ]
    positions = compute_positions(events)
    source = positions[(ACCOUNT_A, INSTRUMENT_X)]
    dest = positions[(ACCOUNT_B, INSTRUMENT_X)]
    assert source.quantity == Decimal("6")
    assert source.cost_basis_eur == Decimal("600.00")
    assert dest.quantity == Decimal("4")
    assert dest.cost_basis_eur == Decimal("400.00")  # original unit cost preserved


def test_opening_balance_seeds_a_lot_like_a_buy():
    events = [
        TxnEvent(
            order=1,
            type=TransactionType.OPENING_BALANCE,
            date=date(2024, 1, 1),
            account_id=ACCOUNT_A,
            instrument_id=INSTRUMENT_X,
            counter_account_id=None,
            quantity=Decimal("412"),
            amount_eur=Decimal("38000.00"),
        )
    ]
    positions = compute_positions(events)
    pos = positions[(ACCOUNT_A, INSTRUMENT_X)]
    assert pos.quantity == Decimal("412")
    assert pos.cost_basis_eur == Decimal("38000.00")
