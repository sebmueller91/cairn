"""The tax view must not crash on a zero-quantity cost-only correction,
and must treat an oversell as impossible rather than returning a gain
computed against a partial cost.

Both were originally bugs in a second, independent FIFO replay that
lived in tax_service. That replay is gone — tax_service now reads
app.ledger's sales log, so these invariants come from the one ledger
authority. The tests stay, pinned at the tax_service boundary: they are
what would catch the regression if anyone reintroduces a shortcut here,
and the zero-quantity case in particular reaches this code through
supersede_service, which emits a zero-quantity OPENING_BALANCE whenever
a backfill explains every share but not the full cost basis
(tests/test_ledger_cost_only.py documents this as the routine outcome).

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
from app.tax_service import realized_sales


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

    gains = realized_sales(db_session)

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

    assert realized_sales(db_session) == []


def test_oversell_raises_instead_of_silently_truncating(db_session):
    """An oversell must raise rather than paper over the impossible state
    with a wrong, partially-costed gain. txn_service.check_holdings stops
    this at write time, so reaching it here means something upstream let a
    corrupt ledger through — which must not pass as a quiet wrong number."""
    _seed_batch(db_session)
    db_session.add_all(
        [
            _txn(1, TransactionType.BUY, "10", "1000", day=1),
            _txn(2, TransactionType.SELL, "15", "1800", day=2),
        ]
    )
    db_session.commit()

    with pytest.raises(InsufficientHoldingError) as exc_info:
        realized_sales(db_session)
    assert exc_info.value.requested == Decimal("15")
    assert exc_info.value.available == Decimal("10")
