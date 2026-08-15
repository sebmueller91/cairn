from datetime import date
from decimal import Decimal

from app.cash_service import derive_portfolio_deposits, interpolate_cash_balance
from app.models import Account, AccountType, Instrument, TransactionType, Txn


def _txn(account_id, txn_type, amount_eur, day, order):
    return Txn(
        external_id=f"t-{order}",
        payload_hash="n/a",
        import_batch_id=1,
        date=day,
        type=txn_type,
        account_id=account_id,
        currency="EUR",
        fees=Decimal(0),
        tax=Decimal(0),
        amount_eur=Decimal(amount_eur),
        source="agent",
    )


def test_derive_deposits_only_on_negative_balance(db_session):
    from app.models import ImportBatch, TxnSource

    account = Account(name="Portfolio A", type=AccountType.BROKERAGE, currency="EUR")
    db_session.add(account)
    db_session.add(ImportBatch(id=1, source=TxnSource.IMPORT))
    db_session.commit()

    txns = [
        _txn(account.id, TransactionType.BUY, "1000.00", date(2024, 1, 1), 1),  # -> deposit 1000
        _txn(account.id, TransactionType.DIVIDEND, "50.00", date(2024, 1, 2), 2),
        _txn(account.id, TransactionType.BUY, "30.00", date(2024, 1, 3), 3),  # balance 20, no deposit
        _txn(account.id, TransactionType.BUY, "100.00", date(2024, 1, 4), 4),  # -> deposit 80
    ]
    db_session.add_all(txns)
    db_session.commit()

    deposits = derive_portfolio_deposits(db_session, account.id)
    assert [(d.date, d.amount_eur) for d in deposits] == [
        (date(2024, 1, 1), Decimal("1000.00")),
        (date(2024, 1, 4), Decimal("80.00")),
    ]


def test_interpolation_without_deposits_is_linear():
    statements = [(date(2024, 1, 1), Decimal("1000")), (date(2024, 1, 11), Decimal("100"))]
    result = interpolate_cash_balance(statements, [])
    assert result[date(2024, 1, 6)] == Decimal("550")
    assert result[date(2024, 1, 11)] == Decimal("100")


def test_interpolation_does_not_double_count_a_known_deposit():
    statements = [(date(2024, 1, 1), Decimal("1000")), (date(2024, 1, 11), Decimal("100"))]
    known_deposits = [(date(2024, 1, 4), Decimal("800"))]

    result = interpolate_cash_balance(statements, known_deposits)

    # Before the deposit: only the small unexplained drift has applied —
    # nowhere near the ~900 total drop, since most of it is the deposit.
    assert result[date(2024, 1, 3)] == Decimal("980")
    # The day the money actually left, the balance already reflects it —
    # not smeared evenly across the full 10-day window.
    assert result[date(2024, 1, 4)] == Decimal("170")
    assert result[date(2024, 1, 11)] == Decimal("100")
