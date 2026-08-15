"""Logical export (spec 6.6, backup layer 2): a schema/app-independent
snapshot of every write primitive — accounts, instruments, transactions,
valuation anchors, loan parameters, manually-entered index points, ETF
look-through compositions, and the target allocation — as CSV plus a
consolidated JSON, bundled into one ZIP. This is what survives a wrecked
migration or the whole application being replaced someday; the SQLite
`.backup` (layer 1) doesn't, since restoring it needs this exact schema
and this exact app.

Deliberately excludes price_point, fx_rate, and daily_snapshot: all three
are refetchable/rebuildable caches (ADR 0003/0010), not data this export
exists to protect.

cpi_index_point and house_price_index_point look like the same kind of
cache but are not: real Destatis credentials require a one-off
registration this app can't complete on its own, so both tables are
hand-entered/maintained (see their model docstrings) and are irreplaceable
if lost — they are exported in full. etf_composition is likewise entered
by hand from ETF factsheets, not derived from anything else in the
database. The target allocation (the single `setting` row under key
`target_allocation`, see allocation_service.py) is user-entered
configuration, not job-run bookkeeping like `last_price_fetch` /
`last_snapshot` (which stay excluded — runtime state, not user data).
"""

import csv
import enum
import io
import json
import zipfile
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.allocation_service import get_targets
from app.models import (
    Account,
    CpiIndexPoint,
    EtfComposition,
    HousePriceIndexPoint,
    Instrument,
    Loan,
    Txn,
    ValuationAnchor,
)

TABLES = (
    "accounts",
    "instruments",
    "transactions",
    "valuation_anchors",
    "loans",
    "cpi_index_points",
    "house_price_index_points",
    "etf_compositions",
    "target_allocation",
)


def _row_dict(obj) -> dict:
    out = {}
    for column in obj.__table__.columns:
        value = getattr(obj, column.name)
        if isinstance(value, Decimal):
            value = str(value)
        elif isinstance(value, (date, datetime)):
            value = value.isoformat()
        elif isinstance(value, enum.Enum):
            value = value.value
        out[column.name] = value
    return out


def build_export(db: Session) -> dict[str, list[dict]]:
    return {
        "accounts": [_row_dict(a) for a in db.query(Account).order_by(Account.id).all()],
        "instruments": [
            _row_dict(i) for i in db.query(Instrument).order_by(Instrument.id).all()
        ],
        "transactions": [_row_dict(t) for t in db.query(Txn).order_by(Txn.id).all()],
        "valuation_anchors": [
            _row_dict(v) for v in db.query(ValuationAnchor).order_by(ValuationAnchor.id).all()
        ],
        "loans": [_row_dict(loan) for loan in db.query(Loan).order_by(Loan.id).all()],
        "cpi_index_points": [
            _row_dict(p) for p in db.query(CpiIndexPoint).order_by(CpiIndexPoint.date).all()
        ],
        "house_price_index_points": [
            _row_dict(p)
            for p in db.query(HousePriceIndexPoint)
            .order_by(HousePriceIndexPoint.series, HousePriceIndexPoint.date)
            .all()
        ],
        "etf_compositions": [
            _row_dict(c)
            for c in db.query(EtfComposition)
            .order_by(
                EtfComposition.instrument_id, EtfComposition.dimension, EtfComposition.category
            )
            .all()
        ],
        "target_allocation": [
            {"asset_class": asset_class, "target_pct": str(pct)}
            for asset_class, pct in sorted(get_targets(db).items())
        ],
    }


def _csv_bytes(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def build_export_zip(db: Session) -> bytes:
    data = build_export(db)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("export.json", json.dumps(data, indent=2, ensure_ascii=False))
        for name in TABLES:
            zf.writestr(f"{name}.csv", _csv_bytes(data[name]))
    return buf.getvalue()
