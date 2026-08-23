"""tax_service.realized_gains must not crash on a zero-quantity cost-only
correction, and must match app.ledger's semantics for it exactly (spec:
the same FIFO rule as app.ledger, replayed a second time).

supersede_service emits a zero-quantity OPENING_BALANCE whenever a
backfill explains every share but not the full cost basis
(tests/test_ledger_cost_only.py documents this as the routine outcome).
Before this fix, `t.amount_eur / t.quantity` divided by zero and made
/api/tax 500 forever after any supersede.

Also covers the second, independent bug in the same replay: an oversell
must raise, not silently truncate to a partial (wrong) cost and return a
gain computed against it — the same InsufficientHoldingError app.ledger
itself raises for the primary ledger.

Invented ISINs and amounts only, per AGENTS.md.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.ledger import InsufficientHoldingError
from app.models import (
    Account,
    AccountType,
    AssetClass,
    ImportBatch,
    Instrument,
    Txn,
    TransactionType,
    TxnSource,
    ValuationMode,
)
from app.tax_service import realized_gains


def _txn(n, type_, qty, amount, account=1, instrument=1, day=1):
    return Txn(
        external_id=f"zq-{n}",
        payload_hash="n/a",
        import_batch_id=1,
        date=date(2025, 1, day),
        type=type_,
        account_id=account,
        instrument_id=instrument,
        quantity=Decimal(qty) if qty is not None else None,
        currency="EUR",
        fees=Decimal(0),
        tax=Decimal(0),
        amount_eur=Decimal(amount),
        source=TxnSource.AGENT,
    )


def _seed_batch(db_session):
    db_session.add(ImportBatch(id=1, source=TxnSource.AGENT))
    db_session.add(Account(id=1, name="Depot", type=AccountType.BROKERAGE, currency="EUR"))
    db_session.add(
        Instrument(
            id=1, name="Test ETF", isin="XX0000009201", asset_class=AssetClass.EQUITY,
            valuation_mode=ValuationMode.MARKET, currency="EUR",
        )
    )
    db_session.commit()


def test_zero_quantity_cost_correction_does_not_crash(db_session):
    _seed_batch(db_session)
    db_session.add_all(
        [
            _txn(1, TransactionType.BUY, "10", "1000", day=1),
            _txn(2, TransactionType.OPENING_BALANCE, "0", "200", day=2),
            _txn(3, TransactionType.SELL, "10", "1500", day=3),
        ]
    )
    db_session.commit()

    gains = realized_gains(db_session)

    # 1500 proceeds against a corrected 1200 basis -> 300, not 500 and not
    # a ZeroDivisionError — matches ledger.py's
    # test_correction_survives_a_later_sale exactly.
    assert len(gains) == 1
    assert gains[0].gain_eur == Decimal("300")


def test_zero_quantity_correction_with_nothing_on_hand_is_a_noop(db_session):
    """No lots to attach to: dropped, not a crash and not a fabricated lot."""
    _seed_batch(db_session)
    db_session.add(_txn(1, TransactionType.OPENING_BALANCE, "0", "500", day=1))
    db_session.commit()

    assert realized_gains(db_session) == []


def test_oversell_raises_instead_of_silently_truncating(db_session):
    """The two FIFO replays (this one and app.ledger's) must agree that an
    oversell is impossible, not paper over a divergence between them with
    a wrong, partially-costed gain."""
    _seed_batch(db_session)
    db_session.add_all(
        [
            _txn(1, TransactionType.BUY, "10", "1000", day=1),
            _txn(2, TransactionType.SELL, "15", "1800", day=2),
        ]
    )
    db_session.commit()

    with pytest.raises(InsufficientHoldingError) as exc_info:
        realized_gains(db_session)
    assert exc_info.value.requested == Decimal("15")
    assert exc_info.value.available == Decimal("10")
