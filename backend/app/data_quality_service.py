"""Data quality panel (spec 4.6): "which valuation is how old, which
price is stale, which position has no cost basis — prevents silent trust
in outdated figures." A read-only aggregation over currently-open
positions; adds no new storage.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.ledger import compute_positions, txn_to_event
from app.models import Instrument, PricePoint, Txn, ValuationAnchor, ValuationMode
from app.valuation_service import current_instrument_value

STALE_PRICE_DAYS = 7
# House/car appraisals are naturally infrequent (spec 3.3/3.4) — a much
# longer threshold than a tradeable instrument's price, so this only
# flags an anchor that's genuinely been left untouched for years.
STALE_VALUATION_DAYS = 730


@dataclass
class DataQualityIssue:
    kind: str
    instrument_id: int
    instrument_name: str
    account_id: int
    detail: str
    age_days: int | None = None


def check_data_quality(db: Session, as_of: date | None = None) -> list[DataQualityIssue]:
    as_of = as_of or date.today()

    txns = db.query(Txn).filter(Txn.voided_at.is_(None), Txn.instrument_id.isnot(None)).all()
    events = [txn_to_event(t) for t in txns]
    positions = compute_positions(events)

    instruments = {i.id: i for i in db.query(Instrument).all()}
    issues: list[DataQualityIssue] = []

    for (account_id, instrument_id), pos in positions.items():
        if pos.quantity == 0:
            continue
        instrument = instruments.get(instrument_id)
        if instrument is None:
            continue

        if pos.cost_basis_eur == 0:
            issues.append(
                DataQualityIssue(
                    kind="no_cost_basis",
                    instrument_id=instrument_id,
                    instrument_name=instrument.name,
                    account_id=account_id,
                    detail="Open position with zero recorded cost basis",
                )
            )

        if instrument.valuation_mode == ValuationMode.MARKET:
            latest_price = (
                db.query(PricePoint)
                .filter(PricePoint.instrument_id == instrument_id)
                .order_by(PricePoint.date.desc())
                .first()
            )
            if latest_price is None:
                issues.append(
                    DataQualityIssue(
                        kind="missing_price",
                        instrument_id=instrument_id,
                        instrument_name=instrument.name,
                        account_id=account_id,
                        detail="No price data at all",
                    )
                )
            else:
                age = (as_of - latest_price.date).days
                if age > STALE_PRICE_DAYS:
                    issues.append(
                        DataQualityIssue(
                            kind="stale_price",
                            instrument_id=instrument_id,
                            instrument_name=instrument.name,
                            account_id=account_id,
                            detail=f"Last price is {age} days old",
                            age_days=age,
                        )
                    )

        elif instrument.valuation_mode in (ValuationMode.ANCHORED, ValuationMode.MODELED):
            if current_instrument_value(db, instrument_id, as_of) is None:
                issues.append(
                    DataQualityIssue(
                        kind="missing_valuation",
                        instrument_id=instrument_id,
                        instrument_name=instrument.name,
                        account_id=account_id,
                        detail="No usable valuation (missing anchor or incomplete config)",
                    )
                )
            elif instrument.valuation_mode == ValuationMode.ANCHORED:
                # MODELED (car) is a continuous formula, not a point-in-
                # time anchor — only ANCHORED (house) has a genuine
                # "how old is the last appraisal" question.
                latest_anchor = (
                    db.query(ValuationAnchor)
                    .filter(ValuationAnchor.instrument_id == instrument_id)
                    .order_by(ValuationAnchor.date.desc())
                    .first()
                )
                age = (as_of - latest_anchor.date).days
                if age > STALE_VALUATION_DAYS:
                    issues.append(
                        DataQualityIssue(
                            kind="stale_valuation",
                            instrument_id=instrument_id,
                            instrument_name=instrument.name,
                            account_id=account_id,
                            detail=f"Last valuation is {age} days old",
                            age_days=age,
                        )
                    )

    return issues
