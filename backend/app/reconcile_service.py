"""spec 7.4 — "the underrated endpoint": an agent reads a statement's
closing holdings and sends them as-is; this compares them against what
the ledger computes and reports exactly where they diverge. Surfaces a
missed savings-plan execution, a split, or a scrip dividend without ever
recounting a position by hand.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.ledger import compute_positions, txn_to_event
from app.models import Txn


def compute_holdings_as_of(
    db: Session, account_id: int, as_of: date
) -> dict[int, Decimal]:
    """Quantity per instrument_id held in this account at close of `as_of`.
    Replays the instrument's full cross-account history up to that date,
    same reasoning as GET /api/positions: a SPLIT or TRANSFER can only be
    computed correctly with the other side of the ledger in view, not by
    querying this account's rows in isolation."""
    txns = (
        db.query(Txn)
        .filter(
            Txn.voided_at.is_(None),
            Txn.instrument_id.isnot(None),
            Txn.date <= as_of,
        )
        .all()
    )
    events = [txn_to_event(t) for t in txns]
    positions = compute_positions(events)
    return {
        instrument_id: pos.quantity
        for (acc_id, instrument_id), pos in positions.items()
        if acc_id == account_id
    }
