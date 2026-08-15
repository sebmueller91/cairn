"""Small key-value store backed by the `setting` table — used for
job-run bookkeeping (last price fetch, last snapshot) that /api/health
reports. Not to be confused with app.config.Settings (env-based app
config); this is persisted, mutable, runtime state.
"""

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import Setting


def get(db: Session, key: str) -> Any | None:
    row = db.get(Setting, key)
    return json.loads(row.value_json) if row else None


def set(db: Session, key: str, value: Any) -> None:
    row = db.get(Setting, key)
    encoded = json.dumps(value)
    if row:
        row.value_json = encoded
    else:
        db.add(Setting(key=key, value_json=encoded))
