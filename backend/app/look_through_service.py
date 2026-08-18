"""ETF look-through (spec 4.4): "a region/sector breakdown maintained per
ETF (entered by hand from the factsheet; it rarely changes). This
reveals that a single share you hold directly also sits inside three of
your ETFs" — implemented at the granularity spec actually asks for
(region/sector percentages per ETF), not individual constituent stocks,
which would need a much larger, unscoped dataset (every holding of every
fund) to mean anything.

For a position whose instrument has composition rows for the requested
dimension, its value is split across those categories by weight. For one
that doesn't (a directly-held stock, or an ETF nobody's entered a
breakdown for yet), the instrument's own `region`/`sector` field is used
instead — a directly-held stock's "breakdown" is trivially 100% of
itself.
"""

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app import kv_store
from app.ledger import compute_positions, txn_to_event
from app.models import EtfComposition, Instrument, Txn, ValuationMode
from app.valuation_service import current_instrument_value

UNKNOWN_CATEGORY = "Unknown"
# An instrument whose region/sector is set to this is left out of that
# dimension entirely, rather than being bucketed. Gold and bitcoin have
# no country of domicile, and parking them under a catch-all makes them
# the third-largest slice of a chart about geography — which shrinks
# every real region's share and answers a question nobody asked. Distinct
# from an empty field, which still means "not entered yet" and shows up
# as Unknown so it can be noticed and fixed.
NOT_APPLICABLE = "n/a"
BENCHMARK_KEY_PREFIX = "look_through_benchmark_"


@dataclass
class LookThroughRow:
    category: str
    value_eur: Decimal


def benchmark_key(dimension: str) -> str:
    return f"{BENCHMARK_KEY_PREFIX}{dimension}"


def get_benchmark(db: Session, dimension: str) -> tuple[str | None, dict[str, Decimal]]:
    """The market-wide split this dimension is compared against — e.g. MSCI
    ACWI for regions. Returns (label, {category: weight_pct})."""
    raw = kv_store.get(db, benchmark_key(dimension)) or {}
    weights = {k: Decimal(str(v)) for k, v in (raw.get("breakdown") or {}).items()}
    return raw.get("label"), weights


def set_benchmark(
    db: Session, dimension: str, label: str, breakdown: dict[str, Decimal]
) -> None:
    total = sum(breakdown.values(), Decimal(0))
    if breakdown and abs(total - Decimal(100)) > Decimal(1):
        raise ValueError(f"benchmark must sum to ~100, got {total}")
    kv_store.set(
        db,
        benchmark_key(dimension),
        {"label": label, "breakdown": {k: str(v) for k, v in breakdown.items()}},
    )


def compute_look_through(
    db: Session, dimension: str, as_of: date | None = None
) -> list[LookThroughRow]:
    as_of = as_of or date.today()

    txns = db.query(Txn).filter(Txn.voided_at.is_(None), Txn.instrument_id.isnot(None)).all()
    events = [txn_to_event(t) for t in txns]
    positions = compute_positions(events)

    instruments = {i.id: i for i in db.query(Instrument).all()}
    composition_rows = (
        db.query(EtfComposition).filter(EtfComposition.dimension == dimension).all()
    )
    composition: dict[int, list[tuple[str, Decimal]]] = {}
    for row in composition_rows:
        composition.setdefault(row.instrument_id, []).append((row.category, row.weight_pct))

    totals: dict[str, Decimal] = {}

    def add(category: str, value: Decimal) -> None:
        totals[category] = totals.get(category, Decimal(0)) + value

    for (_, instrument_id), pos in positions.items():
        if pos.quantity == 0:
            continue
        instrument = instruments.get(instrument_id)
        if instrument is None or instrument.valuation_mode != ValuationMode.MARKET:
            continue
        price = current_instrument_value(db, instrument_id, as_of)
        if price is None:
            continue
        value = pos.quantity * price

        breakdown = composition.get(instrument_id)
        if breakdown:
            for category, weight_pct in breakdown:
                add(category, value * weight_pct / Decimal(100))
        else:
            own = instrument.region if dimension == "region" else instrument.sector
            if own == NOT_APPLICABLE:
                continue
            add(own or UNKNOWN_CATEGORY, value)

    return [
        LookThroughRow(category=k, value_eur=v)
        for k, v in sorted(totals.items(), key=lambda kv: kv[0])
    ]


# The three region buckets this taxonomy treats as emerging. "Middle East &
# Africa" is the imprecise one — MSCI counts Israel as developed and Saudi
# Arabia and South Africa as emerging, and the single bucket cannot separate
# them. It sits on the emerging side because that is where the bulk of the
# weight is; at ~1.5% of a world index the rounding is smaller than the drift
# the compositions themselves accumulate between factsheet updates.
EMERGING_CATEGORIES = frozenset({"Emerging Asia", "Latin America", "Middle East & Africa"})

ETF_SPLIT_TARGET_KEY = "etf_emerging_target_pct"
ETF_TAG = "etf"


@dataclass
class EtfSplitRow:
    instrument_id: int
    name: str
    value_eur: Decimal
    emerging_eur: Decimal
    emerging_pct: Decimal


@dataclass
class EtfSplit:
    """Developed vs. emerging exposure across the fund holdings only.

    Answers the question a 70/30 World/EM plan actually asks, which whole-fund
    bucketing cannot: an all-world fund is not "a World ETF" or "an EM ETF",
    it is both at once, and its emerging share belongs on the emerging side.
    Every fund contributes its true weight, so adding another one never
    requires deciding which bucket it goes in.
    """

    developed_eur: Decimal
    emerging_eur: Decimal
    total_eur: Decimal
    emerging_pct: Decimal | None
    target_emerging_pct: Decimal | None
    drift_pp: Decimal | None
    rows: list[EtfSplitRow]


def get_etf_split_target(db: Session) -> Decimal | None:
    raw = kv_store.get(db, ETF_SPLIT_TARGET_KEY)
    return Decimal(str(raw)) if raw is not None else None


def set_etf_split_target(db: Session, pct: Decimal | None) -> None:
    """`None` clears the target and puts the card back to plain reporting."""
    if pct is None:
        kv_store.set(db, ETF_SPLIT_TARGET_KEY, None)
        return
    if not (Decimal(0) <= pct <= Decimal(100)):
        raise ValueError(f"target must be between 0 and 100, got {pct}")
    kv_store.set(db, ETF_SPLIT_TARGET_KEY, str(pct))


def compute_etf_split(db: Session, as_of: date | None = None) -> EtfSplit:
    as_of = as_of or date.today()

    txns = db.query(Txn).filter(Txn.voided_at.is_(None), Txn.instrument_id.isnot(None)).all()
    positions = compute_positions([txn_to_event(t) for t in txns])
    instruments = {i.id: i for i in db.query(Instrument).all()}

    region_rows = (
        db.query(EtfComposition).filter(EtfComposition.dimension == "region").all()
    )
    composition: dict[int, list[tuple[str, Decimal]]] = {}
    for row in region_rows:
        composition.setdefault(row.instrument_id, []).append((row.category, row.weight_pct))

    rows: list[EtfSplitRow] = []
    developed = Decimal(0)
    emerging = Decimal(0)

    for (_, instrument_id), pos in positions.items():
        if pos.quantity == 0:
            continue
        instrument = instruments.get(instrument_id)
        if instrument is None or instrument.valuation_mode != ValuationMode.MARKET:
            continue
        # tags live as a JSON string on the model (models.py:tags_json);
        # the list shape only exists at the schema boundary.
        if ETF_TAG not in json.loads(instrument.tags_json or "[]"):
            continue
        price = current_instrument_value(db, instrument_id, as_of)
        if price is None:
            continue

        value = pos.quantity * price
        breakdown = composition.get(instrument_id, [])
        # A fund with no breakdown counts as fully developed rather than being
        # dropped: dropping it would quietly shrink the denominator and make
        # the emerging share read high. data_quality already flags the missing
        # breakdown itself.
        em = sum(
            (value * weight / Decimal(100) for category, weight in breakdown
             if category in EMERGING_CATEGORIES),
            Decimal(0),
        )
        developed += value - em
        emerging += em
        rows.append(
            EtfSplitRow(
                instrument_id=instrument_id,
                name=instrument.name,
                value_eur=value,
                emerging_eur=em,
                emerging_pct=(em / value * Decimal(100)) if value else Decimal(0),
            )
        )

    total = developed + emerging
    emerging_pct = (emerging / total * Decimal(100)) if total else None
    target = get_etf_split_target(db)
    drift = (emerging_pct - target) if (emerging_pct is not None and target is not None) else None

    rows.sort(key=lambda r: r.value_eur, reverse=True)
    return EtfSplit(
        developed_eur=developed,
        emerging_eur=emerging,
        total_eur=total,
        emerging_pct=emerging_pct,
        target_emerging_pct=target,
        drift_pp=drift,
        rows=rows,
    )
