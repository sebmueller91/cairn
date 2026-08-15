"""Target allocation & drift (spec 4.4): targets per asset class stored via
the generic setting key-value store, compared against actual current
allocation, plus a rebalancing proposal — including a purchases-only mode
that never sells, distributing the next contribution across underweight
classes instead.

Scope: MARKET-valuation instrument positions only, the same "investable
positions" universe as performance_service.py/attribution_service.py use
for their own return metrics — target-allocation rebalancing is
inherently about buying/selling instruments, which doesn't apply to a raw
CASH-type account's checking balance the same way (see
performance_service.py's module docstring for the fuller reasoning behind
that scope boundary elsewhere in the app).
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app import kv_store
from app.models import DailySnapshot, Instrument, ValuationMode

TARGET_ALLOCATION_KEY = "target_allocation"


def get_targets(db: Session) -> dict[str, Decimal]:
    raw = kv_store.get(db, TARGET_ALLOCATION_KEY) or {}
    return {k: Decimal(str(v)) for k, v in raw.items()}


def set_targets(db: Session, targets: dict[str, Decimal]) -> None:
    total = sum(targets.values(), Decimal(0))
    if targets and total != Decimal(100):
        raise ValueError(f"targets must sum to 100, got {total}")
    kv_store.set(db, TARGET_ALLOCATION_KEY, {k: str(v) for k, v in targets.items()})


def current_allocation(db: Session) -> dict[str, Decimal]:
    """Value per asset class as of the most recent day any MARKET
    position exists."""
    latest = (
        db.query(DailySnapshot.date)
        .filter(DailySnapshot.scope_type == "position")
        .order_by(DailySnapshot.date.desc())
        .first()
    )
    if latest is None:
        return {}
    latest_date = latest[0]

    instruments = {
        i.id: i
        for i in db.query(Instrument).filter(Instrument.valuation_mode == ValuationMode.MARKET)
    }
    rows = (
        db.query(DailySnapshot)
        .filter(DailySnapshot.scope_type == "position", DailySnapshot.date == latest_date)
        .all()
    )
    by_class: dict[str, Decimal] = {}
    for row in rows:
        instrument_id = int(row.scope_id.split(":")[1])
        instrument = instruments.get(instrument_id)
        if instrument is None:
            continue
        key = instrument.asset_class.value
        by_class[key] = by_class.get(key, Decimal(0)) + row.value_eur
    return by_class


@dataclass
class DriftRow:
    asset_class: str
    current_value: Decimal
    current_pct: Decimal
    target_pct: Decimal
    drift_pp: Decimal  # current_pct - target_pct
    drift_value: Decimal  # current_value - target_value (positive = overweight)


def compute_drift(
    current: dict[str, Decimal], targets: dict[str, Decimal]
) -> list[DriftRow]:
    total = sum(current.values(), Decimal(0))
    classes = sorted(set(current) | set(targets))
    rows = []
    for cls in classes:
        current_value = current.get(cls, Decimal(0))
        target_pct = targets.get(cls, Decimal(0))
        current_pct = (current_value / total * 100) if total else Decimal(0)
        target_value = (target_pct / 100) * total
        rows.append(
            DriftRow(
                asset_class=cls,
                current_value=current_value,
                current_pct=current_pct,
                target_pct=target_pct,
                drift_pp=current_pct - target_pct,
                drift_value=current_value - target_value,
            )
        )
    return rows


@dataclass
class RebalanceProposal:
    asset_class: str
    amount: Decimal  # positive = buy this much, negative = sell this much


def full_rebalance_proposal(drift: list[DriftRow]) -> list[RebalanceProposal]:
    """Standard mode: buy/sell exactly enough to hit every target."""
    return [
        RebalanceProposal(asset_class=row.asset_class, amount=-row.drift_value)
        for row in drift
        if row.drift_value != 0
    ]


def purchases_only_proposal(
    drift: list[DriftRow], contribution: Decimal
) -> list[RebalanceProposal]:
    """No selling: distribute `contribution` across underweight classes
    only, proportional to each one's shortfall. If it's more than enough
    to close every gap, top every underweight class up to target first,
    then spread the remainder across *all* target classes by their
    target weight — nothing left to correct, so the leftover should just
    track the target mix."""
    if contribution <= 0:
        return []

    underweight = [row for row in drift if row.drift_value < 0]
    total_shortfall = -sum((row.drift_value for row in underweight), Decimal(0))
    target_total = sum((row.target_pct for row in drift), Decimal(0))

    if total_shortfall == 0:
        if target_total == 0:
            return []
        return [
            RebalanceProposal(
                asset_class=row.asset_class,
                amount=contribution * row.target_pct / target_total,
            )
            for row in drift
            if row.target_pct > 0
        ]

    if contribution <= total_shortfall:
        return [
            RebalanceProposal(
                asset_class=row.asset_class,
                amount=contribution * (-row.drift_value) / total_shortfall,
            )
            for row in underweight
        ]

    proposals: dict[str, Decimal] = {row.asset_class: -row.drift_value for row in underweight}
    remainder = contribution - total_shortfall
    if target_total > 0:
        for row in drift:
            if row.target_pct <= 0:
                continue
            proposals[row.asset_class] = (
                proposals.get(row.asset_class, Decimal(0))
                + remainder * row.target_pct / target_total
            )
    return [
        RebalanceProposal(asset_class=k, amount=v) for k, v in proposals.items() if v != 0
    ]
