"""Tax-informational view (spec 4.6, explicitly non-binding — not tax
advice): saver's-allowance usage, unrealised P/L with an *estimated* tax
charge on sale, and a January reminder about the Vorabpauschale (advance
lump sum). FIFO cost basis per position is already available via
/api/positions and isn't duplicated here.
"""

from collections import deque
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.ledger import compute_positions, txn_to_event
from app.models import Instrument, Txn, TransactionType, ValuationMode
from app.valuation_service import current_instrument_value

# Germany's flat capital-gains tax (Abgeltungsteuer) + solidarity
# surcharge — a reasonable illustrative default, not this year's
# authoritative rate; church tax varies by state and isn't modeled.
# Purely informational (spec 4.6: "explicitly non-binding").
DEFAULT_CAPITAL_GAINS_TAX_RATE = Decimal("0.25")
DEFAULT_SOLIDARITY_SURCHARGE_RATE = Decimal("0.055")  # of the tax amount, not of the gain


@dataclass
class RealizedGain:
    date: date
    account_id: int
    instrument_id: int
    gain_eur: Decimal


def realized_gains(db: Session) -> list[RealizedGain]:
    """Replays BUY/SELL/TRANSFER/SPLIT in ledger order — the same FIFO
    rule as app.ledger — but records each SELL's own realized gain dated
    to when it happened. ledger.py's compute_positions only exposes a
    lifetime total per (account, instrument), not one broken out by
    year, which the saver's-allowance check needs; kept as a separate
    small replay here rather than changing that function's return shape,
    which several other modules already depend on."""
    txns = (
        db.query(Txn)
        .filter(Txn.voided_at.is_(None), Txn.instrument_id.isnot(None))
        .order_by(Txn.date, Txn.id)
        .all()
    )
    lots: dict[tuple[int, int], deque] = {}
    gains: list[RealizedGain] = []

    def queue(account_id: int, instrument_id: int) -> deque:
        return lots.setdefault((account_id, instrument_id), deque())

    for t in txns:
        if t.type in (TransactionType.BUY, TransactionType.OPENING_BALANCE):
            queue(t.account_id, t.instrument_id).append([t.quantity, t.amount_eur / t.quantity])

        elif t.type == TransactionType.SELL:
            q = queue(t.account_id, t.instrument_id)
            remaining = t.quantity
            cost = Decimal(0)
            while remaining > 0 and q:
                lot_qty, lot_unit_cost = q[0]
                take = min(lot_qty, remaining)
                cost += take * lot_unit_cost
                lot_qty -= take
                remaining -= take
                if lot_qty == 0:
                    q.popleft()
                else:
                    q[0][0] = lot_qty
            gains.append(
                RealizedGain(
                    date=t.date,
                    account_id=t.account_id,
                    instrument_id=t.instrument_id,
                    gain_eur=t.amount_eur - cost,
                )
            )

        elif t.type == TransactionType.TRANSFER:
            src = queue(t.account_id, t.instrument_id)
            dst = queue(t.counter_account_id, t.instrument_id)
            remaining = t.quantity
            while remaining > 0 and src:
                lot_qty, lot_unit_cost = src[0]
                take = min(lot_qty, remaining)
                dst.append([take, lot_unit_cost])
                lot_qty -= take
                remaining -= take
                if lot_qty == 0:
                    src.popleft()
                else:
                    src[0][0] = lot_qty

        elif t.type == TransactionType.SPLIT:
            for key, q in lots.items():
                if key[1] != t.instrument_id:
                    continue
                for lot in q:
                    lot[0] *= t.split_ratio
                    lot[1] /= t.split_ratio

    return gains


def saver_allowance_usage(db: Session, year: int, allowance_eur: Decimal) -> dict:
    gains_this_year = sum(
        (g.gain_eur for g in realized_gains(db) if g.date.year == year), Decimal(0)
    )
    income_txns = (
        db.query(Txn)
        .filter(
            Txn.voided_at.is_(None),
            Txn.type.in_([TransactionType.DIVIDEND, TransactionType.INTEREST]),
            Txn.date >= date(year, 1, 1),
            Txn.date <= date(year, 12, 31),
        )
        .all()
    )
    income = sum((t.amount_eur for t in income_txns), Decimal(0))
    total = gains_this_year + income
    return {
        "year": year,
        "allowance_eur": allowance_eur,
        "realized_gains_eur": gains_this_year,
        "investment_income_eur": income,
        "total_eur": total,
        "remaining_eur": allowance_eur - total,
    }


@dataclass
class UnrealizedTaxEstimate:
    account_id: int
    instrument_id: int
    quantity: Decimal
    cost_basis_eur: Decimal
    current_value_eur: Decimal
    unrealized_pl_eur: Decimal
    estimated_tax_eur: Decimal


def unrealized_tax_estimates(
    db: Session,
    remaining_allowance_eur: Decimal = Decimal(0),
    tax_rate: Decimal = DEFAULT_CAPITAL_GAINS_TAX_RATE,
    solidarity_rate: Decimal = DEFAULT_SOLIDARITY_SURCHARGE_RATE,
    as_of: date | None = None,
) -> list[UnrealizedTaxEstimate]:
    """Estimated tax if every open position were sold today, netting the
    combined gain against whatever saver's-allowance headroom remains —
    illustrative only (spec 4.6), never advice: no cross-position loss
    offsetting order guarantee beyond position iteration order, no
    church tax, no partial-sale optimisation."""
    as_of = as_of or date.today()
    txns = db.query(Txn).filter(Txn.voided_at.is_(None), Txn.instrument_id.isnot(None)).all()
    events = [txn_to_event(t) for t in txns]
    positions = compute_positions(events)
    instruments = {i.id: i for i in db.query(Instrument).all()}

    rows: list[UnrealizedTaxEstimate] = []
    allowance_used = Decimal(0)
    for (account_id, instrument_id), pos in positions.items():
        if pos.quantity == 0:
            continue
        instrument = instruments.get(instrument_id)
        if instrument is None or instrument.valuation_mode != ValuationMode.MARKET:
            continue
        price = current_instrument_value(db, instrument_id, as_of)
        if price is None:
            continue
        current_value = pos.quantity * price
        unrealized = current_value - pos.cost_basis_eur

        tax = Decimal(0)
        if unrealized > 0:
            headroom = max(remaining_allowance_eur - allowance_used, Decimal(0))
            taxable = max(unrealized - headroom, Decimal(0))
            allowance_used += min(unrealized, headroom)
            tax = taxable * tax_rate * (Decimal(1) + solidarity_rate)

        rows.append(
            UnrealizedTaxEstimate(
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=pos.quantity,
                cost_basis_eur=pos.cost_basis_eur,
                current_value_eur=current_value,
                unrealized_pl_eur=unrealized,
                estimated_tax_eur=tax,
            )
        )
    return rows


def vorabpauschale_reminder(db: Session, as_of: date | None = None) -> str | None:
    """spec 4.6: "a reminder about the January advance lump sum" — the
    precise Vorabpauschale formula needs the Bundesbank's annually
    published Basiszins, an external figure this app has no source to
    fetch (same story as CPI/house-index/Destatis elsewhere). A reminder,
    not a calculation, exactly as spec asks for — only shown in January,
    and only if there's actually something held it could apply to."""
    as_of = as_of or date.today()
    if as_of.month != 1:
        return None
    txns = db.query(Txn).filter(Txn.voided_at.is_(None), Txn.instrument_id.isnot(None)).all()
    events = [txn_to_event(t) for t in txns]
    positions = compute_positions(events)
    instruments = {i.id: i for i in db.query(Instrument).all()}
    names = sorted(
        {
            instruments[iid].name
            for (_, iid), pos in positions.items()
            if pos.quantity != 0
            and iid in instruments
            and instruments[iid].valuation_mode == ValuationMode.MARKET
        }
    )
    if not names:
        return None
    return (
        "January: check whether the Vorabpauschale (advance lump sum) applies to "
        "any accumulating funds you hold (" + ", ".join(names) + ") — this app doesn't "
        "calculate it (needs the Bundesbank's annual Basiszins), just a reminder to check."
    )
