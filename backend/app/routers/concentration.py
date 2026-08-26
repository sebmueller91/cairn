"""Concentration and structure (spec 4.4).

Two read-only views over the latest snapshot:

- `/api/allocation/breakdown` — value per bucket along one of spec 7.1's
  dimensions. Mounted as a sub-resource rather than on `/api/allocation`
  itself, which spec 7.1 names for this: that path was already taken by
  the target-allocation drift/rebalance response, and overloading one
  path with two unrelated response shapes would be worse than a slightly
  longer URL. The `dimension` and `scope` vocabularies are the spec's,
  unchanged.
- `/api/concentration` — top-N share, HHI and largest single weight.

`region` is deliberately absent from the dimensions. `/api/look-through`
already answers region and sector properly, weighting each fund by its
own composition; a naive breakdown of `instrument.region` would be a
second, worse answer to the same question, and the two would disagree.
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import get_scope
from app.concentration_service import (
    effective_holdings,
    herfindahl_index,
    largest_share,
    top_n_share,
)
from app.database import get_db
from app.models import Account, DailySnapshot, Instrument, ValuationMode
from app.performance_query import latest_snapshot_date
from app.schemas import (
    AllocationBreakdownResponse,
    AllocationBucketRead,
    ConcentrationHoldingRead,
    ConcentrationResponse,
)

router = APIRouter(tags=["structure"])

VALID_DIMENSIONS = ("asset_class", "account", "currency", "liquidity")
VALID_SCOPES = ("investable", "gross", "net")

# Spec 4.4 says "top-10 positions as a share". Adjustable, but bounded —
# a top_n of zero has no meaning and a huge one is just "everything".
MIN_TOP_N, MAX_TOP_N = 1, 100

# Mirrors snapshot_service.rebuild_snapshots exactly: 'investable' is
# MARKET positions plus cash balances, 'gross' adds the ANCHORED/MODELED
# physical assets, 'net' subtracts loans. Defined by valuation mode, not
# asset class — a breakdown drawn along a different boundary would
# disagree with the net-worth figure on every other page while looking
# entirely reasonable on its own. tests/test_structure_endpoints.py
# asserts the sums against /api/timeseries/networth for exactly that
# reason.
_PHYSICAL_MODES = (ValuationMode.ANCHORED, ValuationMode.MODELED)


def _latest_rows(db: Session, scope: str) -> list[DailySnapshot]:
    """Every snapshot row that belongs to `scope` on the most recent day
    the engine has materialised."""
    as_of = latest_snapshot_date(db)
    if as_of is None:
        return []
    wanted = ["position", "cash_account"]
    if scope == "net":
        wanted.append("loan")
    return (
        db.query(DailySnapshot)
        .filter(DailySnapshot.date == as_of, DailySnapshot.scope_type.in_(wanted))
        .all()
    )


def _instrument_of(row: DailySnapshot, instruments: dict[int, Instrument]):
    if row.scope_type != "position":
        return None
    return instruments.get(int(row.scope_id.split(":")[1]))


def _in_scope(row: DailySnapshot, instrument: Instrument | None, scope: str) -> bool:
    if row.scope_type == "cash_account":
        return True
    if row.scope_type == "loan":
        return scope == "net"
    if instrument is None:
        return False
    if instrument.valuation_mode == ValuationMode.MARKET:
        return True
    if instrument.valuation_mode in _PHYSICAL_MODES:
        return scope in ("gross", "net")
    return False


@router.get("/api/allocation/breakdown", response_model=AllocationBreakdownResponse)
def get_allocation_breakdown(
    dimension: str = "asset_class",
    # spec 4.1's default perspective: "if the house is 60 % of total
    # wealth, an equity share of 18 % of total wealth isn't actionable".
    scope: str = "investable",
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> AllocationBreakdownResponse:
    if dimension not in VALID_DIMENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_dimension", "params": {"dimension": dimension}},
        )
    if scope not in VALID_SCOPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_scope", "params": {"scope": scope}},
        )

    instruments = {i.id: i for i in db.query(Instrument).all()}
    accounts = {a.id: a for a in db.query(Account).all()}

    buckets: dict[tuple[str, str], Decimal] = {}
    for row in _latest_rows(db, scope):
        instrument = _instrument_of(row, instruments)
        if not _in_scope(row, instrument, scope):
            continue

        if row.scope_type == "position":
            account_id = int(row.scope_id.split(":")[0])
        else:
            account_id = int(row.scope_id)
        account = accounts.get(account_id)

        if dimension == "asset_class":
            if row.scope_type == "cash_account":
                key = label = "CASH"
            elif row.scope_type == "loan":
                key = label = "LIABILITY"
            else:
                key = label = instrument.asset_class.value
        elif dimension == "account":
            key = str(account_id)
            label = account.name if account else key
        elif dimension == "currency":
            # The instrument's own quote currency, or the account's for a
            # cash balance. A EUR-quoted fund full of dollar assets is
            # beyond what this can see — that is what look-through would
            # be for — but an explicitly USD instrument must not read as
            # EUR merely because its value is converted for display.
            if row.scope_type == "position":
                key = instrument.currency
            elif account is not None:
                key = account.currency
            else:
                key = "EUR"
            label = key
        else:  # liquidity
            tier = instrument.liquidity_tier if row.scope_type == "position" else None
            # Unset stays unset. Bucketing a cash balance under "T0
            # immediate" would be inventing a domain rule, and the field
            # is nullable and mostly unfilled — surfacing that is more
            # useful than hiding it behind a plausible guess.
            key = label = tier.value if tier is not None else ""

        buckets[(key, label)] = buckets.get((key, label), Decimal(0)) + row.value_eur

    ordered = sorted(buckets.items(), key=lambda kv: kv[1], reverse=True)
    return AllocationBreakdownResponse(
        dimension=dimension,
        scope=scope,
        total_eur=sum(buckets.values(), Decimal(0)),
        buckets=[
            AllocationBucketRead(key=key, label=label, value_eur=value)
            for (key, label), value in ordered
        ],
    )


@router.get("/api/concentration", response_model=ConcentrationResponse)
def get_concentration(
    top_n: int = Query(default=10),
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> ConcentrationResponse:
    """How lopsided the tradeable book is.

    Scope is MARKET-valuation positions grouped by instrument — not the
    whole of net worth. A house is typically most of a household's wealth
    and would pin "largest single weight" to itself forever, which is not
    the question spec 4.4 asks ("largest single-stock weight"). Grouping
    by instrument rather than by position also means the same fund held
    in two accounts counts once, which is what concentration means.
    """
    if not MIN_TOP_N <= top_n <= MAX_TOP_N:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_top_n", "params": {"top_n": top_n}},
        )

    instruments = {
        i.id: i
        for i in db.query(Instrument).filter(
            Instrument.valuation_mode == ValuationMode.MARKET
        )
    }
    by_instrument: dict[int, Decimal] = {}
    for row in _latest_rows(db, "investable"):
        if row.scope_type != "position":
            continue
        instrument_id = int(row.scope_id.split(":")[1])
        if instrument_id not in instruments:
            continue
        by_instrument[instrument_id] = (
            by_instrument.get(instrument_id, Decimal(0)) + row.value_eur
        )

    # A fully sold position keeps its snapshot row at zero; it holds
    # nothing and therefore has no share of a concentration measure.
    held = {k: v for k, v in by_instrument.items() if v > 0}
    values = list(held.values())
    total = sum(values, Decimal(0))

    holdings = [
        ConcentrationHoldingRead(
            instrument_id=instrument_id,
            name=instruments[instrument_id].name,
            asset_class=instruments[instrument_id].asset_class.value,
            value_eur=value,
            share=float(value / total),
        )
        for instrument_id, value in sorted(
            held.items(), key=lambda kv: kv[1], reverse=True
        )
    ] if total > 0 else []

    return ConcentrationResponse(
        top_n=top_n,
        holdings_count=len(held),
        total_eur=total,
        hhi=herfindahl_index(values),
        effective_holdings=effective_holdings(values),
        top_n_share=top_n_share(values, top_n),
        largest_share=largest_share(values),
        holdings=holdings,
    )
