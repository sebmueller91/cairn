from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import audit
from app.auth import require_write_scope
from app.database import get_db
from app.models import ImportBatch, Txn, TxnSource
from app.schemas import SupersedeDeltaReport, SupersedeRequest, SupersedeResponse
from app.supersede_service import (
    DEFAULT_COST_BASIS_TOLERANCE_EUR,
    DEFAULT_QUANTITY_TOLERANCE,
    run_supersede,
)

router = APIRouter(prefix="/api/import-batches", tags=["import-batches"])


@router.delete("/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
def rollback_import_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> None:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "import_batch_not_found", "params": {"id": batch_id}},
        )
    txns = db.query(Txn).filter(Txn.import_batch_id == batch_id).all()
    deleted_ids = [t.id for t in txns]
    for txn in txns:
        db.delete(txn)
    # No ORM relationship() is declared between Txn and ImportBatch (there
    # was no other need for one), so the session's automatic flush-order
    # dependency sort doesn't know to delete child rows before the parent
    # — flush explicitly first or the FK constraint fails.
    db.flush()
    db.delete(batch)
    audit.record(
        db,
        actor=TxnSource.AGENT,
        action="delete",
        entity="import_batch",
        entity_id=batch_id,
        payload_hash="n/a",
        diff={"deleted_txn_ids": deleted_ids},
    )
    db.commit()


@router.post("/{batch_id}/supersede", response_model=SupersedeResponse)
def supersede_import_batch(
    batch_id: int,
    body: SupersedeRequest,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> SupersedeResponse:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "import_batch_not_found", "params": {"id": batch_id}},
        )

    reports = run_supersede(
        db,
        batch_id,
        quantity_tolerance=body.quantity_tolerance or DEFAULT_QUANTITY_TOLERANCE,
        cost_basis_tolerance_eur=body.cost_basis_tolerance_eur
        or DEFAULT_COST_BASIS_TOLERANCE_EUR,
    )
    audit.record(
        db,
        actor=TxnSource.AGENT,
        action="update",
        entity="import_batch",
        entity_id=batch_id,
        payload_hash="n/a",
        diff={
            "action": "supersede",
            "opening_balances_voided": [r.opening_balance_txn_id for r in reports],
        },
    )
    db.commit()
    return SupersedeResponse(
        reports=[
            SupersedeDeltaReport(
                account_id=r.account_id,
                instrument_id=r.instrument_id,
                opening_balance_txn_id=r.opening_balance_txn_id,
                original_quantity=r.original_quantity,
                original_cost_basis_eur=r.original_cost_basis_eur,
                recomputed_quantity=r.recomputed_quantity,
                recomputed_cost_basis_eur=r.recomputed_cost_basis_eur,
                matched=r.matched,
                residual_txn_id=r.residual_txn_id,
            )
            for r in reports
        ]
    )
