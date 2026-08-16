"""Zero-quantity OPENING_BALANCE = pure cost-basis correction.

supersede emits one of these whenever backfilled history explains the
share count exactly but not the cost basis — which is the common case
when a broker's Einstandswert includes purchases the backfill doesn't
cover. Before this was handled, compute_positions divided the amount by
a zero quantity and every position query 500'd.
"""

from datetime import date
from decimal import Decimal

from app.ledger import TxnEvent, compute_positions
from app.models import TransactionType


def _event(n, type_, qty, amount, instrument=1, account=1):
    return TxnEvent(
        order=n, date=date(2025, 1, n), type=type_, account_id=account,
        instrument_id=instrument, quantity=Decimal(qty), amount_eur=Decimal(amount),
        counter_account_id=None, split_ratio=None,
    )


def test_zero_quantity_opening_balance_adjusts_cost_without_crashing():
    positions = compute_positions([
        _event(1, TransactionType.BUY, "10", "1000"),
        _event(2, TransactionType.OPENING_BALANCE, "0", "200"),
    ])
    pos = positions[(1, 1)]
    assert pos.quantity == Decimal(10)
    assert pos.cost_basis_eur == Decimal(1200)


def test_negative_cost_only_correction_reduces_basis():
    positions = compute_positions([
        _event(1, TransactionType.BUY, "10", "1000"),
        _event(2, TransactionType.OPENING_BALANCE, "0", "-250"),
    ])
    assert positions[(1, 1)].cost_basis_eur == Decimal(750)


def test_correction_spreads_proportionally_over_lots():
    # Lots of 100 and 300 EUR cost -> a 40 EUR correction splits 10/30.
    positions = compute_positions([
        _event(1, TransactionType.BUY, "10", "100"),
        _event(2, TransactionType.BUY, "10", "300"),
        _event(3, TransactionType.OPENING_BALANCE, "0", "40"),
    ])
    pos = positions[(1, 1)]
    assert pos.cost_basis_eur == Decimal(440)
    assert [lot.quantity * lot.unit_cost_eur for lot in pos.lots] == [
        Decimal(110), Decimal(330),
    ]


def test_correction_survives_a_later_sale():
    """The adjusted basis has to flow into realized P/L, not be discarded."""
    positions = compute_positions([
        _event(1, TransactionType.BUY, "10", "1000"),
        _event(2, TransactionType.OPENING_BALANCE, "0", "200"),
        _event(3, TransactionType.SELL, "10", "1500"),
    ])
    # 1500 proceeds against a corrected 1200 basis -> 300, not 500.
    assert positions[(1, 1)].realized_pl_eur == Decimal(300)


def test_correction_with_nothing_on_hand_is_dropped():
    """No lots to attach to: keep it a no-op rather than inventing a
    share-less lot that would break FIFO on the next purchase."""
    positions = compute_positions([
        _event(1, TransactionType.OPENING_BALANCE, "0", "500"),
    ])
    assert positions == {}


def test_zero_quantity_zero_amount_is_a_noop():
    positions = compute_positions([
        _event(1, TransactionType.BUY, "5", "500"),
        _event(2, TransactionType.OPENING_BALANCE, "0", "0"),
    ])
    assert positions[(1, 1)].cost_basis_eur == Decimal(500)
