from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import audit
from app.auth import require_write_scope
from app.database import get_db
from app.models import ImportBatch, Txn, TxnSource

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
