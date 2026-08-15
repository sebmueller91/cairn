"""Backfill overlap resolution (spec 2.5, mechanism 2).

Workflow: an account starts from a provisional OPENING_BALANCE at some
cutoff date. Months later, the real pre-cutoff history arrives as its own
import batch. Calling supersede on that batch's id recomputes what the
holding at the cutoff *should* be from real history alone and reconciles
it against the provisional entry — voiding it on a match, leaving a
flagged residual on a mismatch. Never silently double-counts.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.ledger import compute_positions, txn_to_event
from app.models import ImportBatch, Txn, TransactionType, TxnSource

DEFAULT_QUANTITY_TOLERANCE = Decimal("0.00000001")
DEFAULT_COST_BASIS_TOLERANCE_EUR = Decimal("0.01")


@dataclass
class DeltaReport:
    account_id: int
    instrument_id: int
    opening_balance_txn_id: int
    original_quantity: Decimal
    original_cost_basis_eur: Decimal
    recomputed_quantity: Decimal
    recomputed_cost_basis_eur: Decimal
    matched: bool
    residual_txn_id: int | None = None


def run_supersede(
    db: Session,
    batch_id: int,
    quantity_tolerance: Decimal = DEFAULT_QUANTITY_TOLERANCE,
    cost_basis_tolerance_eur: Decimal = DEFAULT_COST_BASIS_TOLERANCE_EUR,
) -> list[DeltaReport]:
    backfill_txns = db.query(Txn).filter(Txn.import_batch_id == batch_id).all()
    touched_pairs = {(t.account_id, t.instrument_id) for t in backfill_txns if t.instrument_id}

    reports: list[DeltaReport] = []
    residual_batch: ImportBatch | None = None

    for account_id, instrument_id in touched_pairs:
        candidates = (
            db.query(Txn)
            .filter(
                Txn.account_id == account_id,
                Txn.instrument_id == instrument_id,
                Txn.type == TransactionType.OPENING_BALANCE,
                Txn.provisional.is_(True),
                Txn.voided_at.is_(None),
            )
            .all()
        )
        for opening_balance in candidates:
            history = (
                db.query(Txn)
                .filter(
                    Txn.account_id == account_id,
                    Txn.instrument_id == instrument_id,
                    Txn.voided_at.is_(None),
                    Txn.id != opening_balance.id,
                    Txn.date <= opening_balance.date,
                )
                .all()
            )
            positions = compute_positions([txn_to_event(t) for t in history])
            pos = positions.get((account_id, instrument_id))
            recomputed_qty = pos.quantity if pos else Decimal(0)
            recomputed_cost = pos.cost_basis_eur if pos else Decimal(0)

            qty_diff = abs(opening_balance.quantity - recomputed_qty)
            cost_diff = abs(opening_balance.amount_eur - recomputed_cost)
            matched = qty_diff <= quantity_tolerance and cost_diff <= cost_basis_tolerance_eur

            report = DeltaReport(
                account_id=account_id,
                instrument_id=instrument_id,
                opening_balance_txn_id=opening_balance.id,
                original_quantity=opening_balance.quantity,
                original_cost_basis_eur=opening_balance.amount_eur,
                recomputed_quantity=recomputed_qty,
                recomputed_cost_basis_eur=recomputed_cost,
                matched=matched,
            )

            # Naive-but-UTC, matching created_at/updated_at's CURRENT_TIMESTAMP
            # convention elsewhere in this schema (spec 6.5: all timestamps
            # stored in UTC).
            opening_balance.voided_at = datetime.now(UTC).replace(tzinfo=None)
            opening_balance.voided_by_batch_id = batch_id

            if not matched:
                residual_qty = opening_balance.quantity - recomputed_qty
                residual_cost = opening_balance.amount_eur - recomputed_cost
                if residual_batch is None:
                    residual_batch = ImportBatch(
                        label=f"supersede residual for batch {batch_id}",
                        source=TxnSource.IMPORT,
                    )
                    db.add(residual_batch)
                    db.flush()
                residual = Txn(
                    external_id=f"supersede-{batch_id}-residual-{opening_balance.id}",
                    payload_hash="n/a",
                    import_batch_id=residual_batch.id,
                    date=opening_balance.date,
                    date_precision=opening_balance.date_precision,
                    type=TransactionType.OPENING_BALANCE,
                    account_id=account_id,
                    instrument_id=instrument_id,
                    quantity=residual_qty,
                    price_mode=opening_balance.price_mode,
                    currency=opening_balance.currency,
                    fees=Decimal(0),
                    tax=Decimal(0),
                    amount_eur=residual_cost,
                    provisional=True,
                    note=(
                        f"Residual after supersede by import batch {batch_id}: "
                        f"unexplained by the backfilled history."
                    ),
                    source=TxnSource.IMPORT,
                )
                db.add(residual)
                db.flush()
                report.residual_txn_id = residual.id

            reports.append(report)

    return reports
