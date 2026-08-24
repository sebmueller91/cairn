"""Manual entry for the Vorabpauschale (advance lump sum) actually
debited by the broker — same pattern and same reason as cpi.py and
house_index.py: the figure depends on the BMF's annually published
Basiszins plus each fund's Teilfreistellung class, neither of which
Cairn has a source for. The January statement states the resulting
amount exactly, so it is recorded rather than reconstructed.

It matters because it is deemed §20 investment income charged in the
first days of January: for a portfolio of accumulating funds it can
consume the whole Sparerpauschbetrag before any sale happens, and a tax
estimate that ignores it hands itself headroom that was already spent.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import audit
from app.auth import get_scope, require_write_scope
from app.database import get_db
from app.models import TxnSource, VorabpauschaleEntry
from app.schemas import VorabpauschaleEntryCreate, VorabpauschaleEntryRead

router = APIRouter(prefix="/api/vorabpauschale", tags=["tax"])


@router.post("", response_model=VorabpauschaleEntryRead, status_code=201)
def upsert_vorabpauschale(
    body: VorabpauschaleEntryCreate,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> VorabpauschaleEntry:
    # This router has no source field to distinguish agent vs. manual UI
    # use — both arrive over the same bearer/cookie auth — so every write
    # here is logged as TxnSource.AGENT, same as cpi.py.
    existing = db.get(VorabpauschaleEntry, body.year)
    if existing:
        before = str(existing.amount_eur)
        existing.amount_eur = body.amount_eur
        existing.note = body.note
        audit.record(
            db,
            actor=TxnSource.AGENT,
            action="update",
            entity="vorabpauschale_entry",
            entity_id=str(body.year),
            payload_hash="n/a",
            diff={"before": before, "after": str(body.amount_eur)},
        )
        db.commit()
        db.refresh(existing)
        return existing
    row = VorabpauschaleEntry(**body.model_dump())
    db.add(row)
    audit.record(
        db,
        actor=TxnSource.AGENT,
        action="create",
        entity="vorabpauschale_entry",
        entity_id=str(body.year),
        payload_hash="n/a",
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("", response_model=list[VorabpauschaleEntryRead])
def list_vorabpauschale(
    db: Session = Depends(get_db), _scope=Depends(get_scope)
) -> list[VorabpauschaleEntry]:
    return db.query(VorabpauschaleEntry).order_by(VorabpauschaleEntry.year).all()


@router.delete("/{year}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vorabpauschale(
    year: int,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> None:
    row = db.get(VorabpauschaleEntry, year)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "params": {"year": year}},
        )
    db.delete(row)
    audit.record(
        db,
        actor=TxnSource.AGENT,
        action="delete",
        entity="vorabpauschale_entry",
        entity_id=str(year),
        payload_hash="n/a",
    )
    db.commit()
