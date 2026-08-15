import json

from sqlalchemy.orm import Session

from app.models import AuditLog, TxnSource


def record(
    db: Session,
    *,
    actor: TxnSource,
    action: str,
    entity: str,
    entity_id: int | str,
    payload_hash: str,
    diff: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor=actor,
            action=action,
            entity=entity,
            entity_id=str(entity_id),
            payload_hash=payload_hash,
            diff_json=json.dumps(diff) if diff is not None else None,
        )
    )
