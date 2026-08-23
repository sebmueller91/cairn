"""Pure app.ledger tests (no ORM/DB — same style as test_ledger.py).
Invented account/instrument ids and numbers only, per AGENTS.md.

Covers:
- bug 6: TRANSFER appended the moved lot to the tail of the destination
  FIFO queue regardless of its acquired_date, so a later SELL there could
  consume out of acquisition order.
- bug 7: a reverse/fractional SPLIT could push a lot's quantity past the
  8dp the DailySnapshot.quantity column accepts, raising ValueError only
  much later (on rebuild-snapshots) instead of being bounded here.
- bug 8: SPLIT divided unit cost by the ratio directly, which drifts for
  any ratio that doesn't divide evenly (3, 7, ...) and shows up as a
  tiny nonzero cost basis / unrealized P/L on an otherwise untouched
  position.
"""

from datetime import date
from decimal import Decimal

from app.ledger import TxnEvent, compute_positions
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


def _transfer(order, d, qty, source, dest, instrument=INSTRUMENT_X):
    return TxnEvent(
        order=order,
        type=TransactionType.TRANSFER,
        date=d,
        account_id=source,
        instrument_id=instrument,
        counter_account_id=dest,
        quantity=Decimal(qty),
        amount_eur=Decimal(0),
    )


def _sell(order, d, qty, amount_eur, account=ACCOUNT_A, instrument=INSTRUMENT_X):
    return TxnEvent(
        order=order,
        type=TransactionType.SELL,
        date=d,
        account_id=account,
        instrument_id=instrument,
        counter_account_id=None,
        quantity=Decimal(qty),
        amount_eur=Decimal(amount_eur),
    )


def _split(order, d, ratio, instrument=INSTRUMENT_X, account=ACCOUNT_A):
    return TxnEvent(
        order=order,
        type=TransactionType.SPLIT,
        date=d,
        account_id=account,
        instrument_id=instrument,
        counter_account_id=None,
        quantity=None,
        amount_eur=Decimal(0),
        split_ratio=Decimal(ratio),
    )


def test_transferred_lot_is_ordered_by_acquired_date_not_transfer_order():
    """Invented scenario: A buys 10 units for 1,000.00 in 2019 (unit cost
    100); B buys 10 units for 2,000.00 in 2020 (unit cost 200); in 2021
    A's 10 units transfer to B; in 2022 B sells 10 units for 3,000.00.
    FIFO must consume the older (2019) lot first, giving realized P/L
    2,000.00 and a remaining basis of 2,000.00 — not the 1,000.00/1,000.00
    a tail-append (transfer-order) queue would produce.
    """
    events = [
        _buy(1, date(2019, 1, 10), "10", "1000.00", account=ACCOUNT_A),
        _buy(2, date(2020, 1, 10), "10", "2000.00", account=ACCOUNT_B),
        _transfer(3, date(2021, 1, 10), "10", ACCOUNT_A, ACCOUNT_B),
        _sell(4, date(2022, 1, 10), "10", "3000.00", account=ACCOUNT_B),
    ]
    positions = compute_positions(events)
    pos = positions[(ACCOUNT_B, INSTRUMENT_X)]
    assert pos.quantity == Decimal("10")
    assert pos.cost_basis_eur == Decimal("2000.00")
    assert pos.realized_pl_eur == Decimal("2000.00")


def test_transferred_lot_inserted_in_the_middle_of_existing_lots():
    """Destination already holds an older lot (2018) *and* a newer one
    (2023) by the time the transfer (of a 2020-dated lot) is processed —
    last, chronologically, since the transfer event itself is dated
    2025. A tail-append would land the transferred lot after the 2023
    one; by acquired_date it belongs between the two.

    Selling 15 units afterwards must consume 2018 (cost 500) then the
    transferred 2020 lot (cost 1000) — not 2018 then 2023 (cost 700),
    which is what a naive append would consume instead, leaving the
    transferred lot untouched.
    """
    events = [
        _buy(1, date(2018, 1, 10), "5", "500.00", account=ACCOUNT_B),
        _buy(2, date(2020, 1, 10), "10", "1000.00", account=ACCOUNT_A),
        _buy(3, date(2023, 1, 10), "5", "700.00", account=ACCOUNT_B),
        _transfer(4, date(2025, 1, 10), "10", ACCOUNT_A, ACCOUNT_B),
        _sell(5, date(2026, 1, 10), "15", "2000.00", account=ACCOUNT_B),
    ]
    positions = compute_positions(events)
    pos = positions[(ACCOUNT_B, INSTRUMENT_X)]
    # cost of sold = 500 (2018) + 1000 (transferred 2020) = 1500
    assert pos.realized_pl_eur == Decimal("500.00")  # 2000 - 1500
    assert pos.quantity == Decimal("5")
    assert pos.cost_basis_eur == Decimal("700.00")  # the untouched 2023 lot


def test_reverse_split_quantizes_quantity_to_eight_decimal_places():
    events = [
        _buy(1, date(2024, 1, 10), "1.23456789", "1000.00"),
        _split(2, date(2024, 3, 1), "0.5"),
    ]
    positions = compute_positions(events)
    pos = positions[(ACCOUNT_A, INSTRUMENT_X)]
    quantized = pos.quantity.as_tuple().exponent
    assert isinstance(quantized, int) and quantized >= -8


def test_split_by_a_non_dividing_ratio_preserves_total_cost_exactly():
    events = [
        _buy(1, date(2024, 1, 10), "10", "100.00"),
        _split(2, date(2024, 3, 1), "3"),
    ]
    positions = compute_positions(events)
    pos = positions[(ACCOUNT_A, INSTRUMENT_X)]
    assert pos.quantity == Decimal("30")
    assert pos.cost_basis_eur == Decimal("100.00")


def test_split_by_non_dividing_ratio_then_full_sale_realizes_exact_pl():
    """The realistic symptom (positions/tax read raw, no rounding): sell
    every post-split unit and the realized P/L must be exactly proceeds
    minus the untouched pre-split total cost (30.00), not a value tainted
    by a ~1E-26 residue from reconstructing cost through a divided-then-
    remultiplied unit cost.

    (A sale exactly at cost, realized_pl == 0, would leave both quantity
    and realized_pl at zero and compute_positions drops that key
    entirely — a deliberate no-op-position filter, not something this
    fix should have to work around — so this proceeds at a markup
    instead.)
    """
    events = [
        _buy(1, date(2024, 1, 10), "10", "100.00"),
        _split(2, date(2024, 3, 1), "3"),
        _sell(3, date(2024, 4, 1), "30", "130.00"),
    ]
    positions = compute_positions(events)
    pos = positions[(ACCOUNT_A, INSTRUMENT_X)]
    assert pos.quantity == Decimal("0")
    assert pos.realized_pl_eur == Decimal("30.00")
