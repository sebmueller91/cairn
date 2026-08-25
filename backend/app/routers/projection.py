"""Forward projection of the wealth curve (spec 4.6).

The maths is in projection_service.py; this router's job is to feed it
real values and — the part that actually matters — to refuse the inputs
that would turn an assumption into a confident-looking lie. See that
module's docstring for why this feature is held to a higher standard than
the ones around it.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import get_scope
from app.database import get_db
from app.milestones_service import trailing_12mo_savings_rate
from app.models import DailySnapshot
from app.projection_service import add_months, deflate_projection, project_wealth
from app.schemas import ProjectionPoint, ProjectionResponse

router = APIRouter(prefix="/api/projection", tags=["projection"])

# Mirrors routers/milestones.py and routers/timeseries.py — spec 4.1's
# three notions of wealth, and the only scope_id values snapshot_service
# writes for scope_type="total".
VALID_SCOPES = ("investable", "gross", "net")

# A projection past a few decades is not a longer answer, it is a
# different kind of claim. The lower bound exists because a zero- or
# negative-year horizon has no meaning, and FastAPI would otherwise hand
# `range()` a negative count and return an empty series with a 200.
MIN_YEARS, MAX_YEARS = 1, 50

# Not domain rules, just guards against inputs that are nonsense for a
# household net worth tracker but parse as perfectly valid Decimals. The
# same reasoning (and the same NaN/Infinity trap) as
# routers/allocation.py's MAX_PLAUSIBLE_CONTRIBUTION_EUR.
MAX_ABS_RATE_PCT = Decimal(100)
MAX_ABS_MONTHLY_SAVINGS_EUR = Decimal(10_000_000)


def _finite(value: Decimal, limit: Decimal) -> bool:
    """Range check, plus a non-finite guard that pydantic already makes
    unreachable over HTTP.

    Decimal("nan")/Decimal("Infinity") parse without raising and would
    otherwise reach the compounding loop and come back as a curve of NaNs
    behind a 200. In practice pydantic rejects them at the query boundary
    first (main.py turns that into the readable {code, params} contract),
    so the `is_finite()` here only matters to a direct caller. It stays
    because it costs nothing and because the range comparisons below are
    all False against NaN — this is written to require a true answer
    rather than to catch a false one."""
    try:
        return value.is_finite() and -limit <= value <= limit
    except InvalidOperation:
        return False


@router.get("", response_model=ProjectionResponse)
def get_projection(
    scope: str = "net",
    years: int = 10,
    # Defaults deliberately match the ones already in the codebase rather
    # than introducing new ones: 5% is routers/milestones.py's assumed
    # return, so the milestone card and this curve start from the same
    # premise. The spread and the inflation rate are presentation
    # choices the caller is expected to move, not house positions.
    annual_return_pct: Decimal = Query(default=Decimal(5)),
    return_spread_pp: Decimal = Query(default=Decimal(2)),
    annual_inflation_pct: Decimal = Query(default=Decimal(2)),
    # None means "use the measured trailing rate". Distinct from 0, which
    # is the legitimate question "what if I stopped contributing".
    monthly_savings_eur: Decimal | None = Query(default=None),
    real: bool = False,
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> ProjectionResponse:
    if scope not in VALID_SCOPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_scope", "params": {"scope": scope}},
        )
    if not MIN_YEARS <= years <= MAX_YEARS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_horizon", "params": {"years": years}},
        )
    for name, value in (
        ("annual_return_pct", annual_return_pct),
        ("return_spread_pp", return_spread_pp),
        ("annual_inflation_pct", annual_inflation_pct),
    ):
        if not _finite(value, MAX_ABS_RATE_PCT):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "invalid_assumption", "params": {name: str(value)}},
            )
    if monthly_savings_eur is not None and not _finite(
        monthly_savings_eur, MAX_ABS_MONTHLY_SAVINGS_EUR
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_assumption",
                "params": {"monthly_savings_eur": str(monthly_savings_eur)},
            },
        )
    # Checked after finiteness, so a NaN spread is reported as the
    # nonsense it is rather than sliding past a `< 0` comparison that is
    # False for NaN.
    if return_spread_pp < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_spread", "params": {"return_spread_pp": str(return_spread_pp)}},
        )

    row = (
        db.query(DailySnapshot)
        .filter(DailySnapshot.scope_type == "total", DailySnapshot.scope_id == scope)
        .order_by(DailySnapshot.date.desc())
        .first()
    )
    savings = (
        monthly_savings_eur
        if monthly_savings_eur is not None
        else trailing_12mo_savings_rate(db)
    )
    source = "override" if monthly_savings_eur is not None else "derived"

    low_pct = annual_return_pct - return_spread_pp
    high_pct = annual_return_pct + return_spread_pp

    if row is None:
        # Nothing recorded to project from. An empty series lets the UI
        # say so; a flat line at zero would look like an answer.
        return ProjectionResponse(
            scope=scope,
            start_date=date.today(),
            start_value_eur=Decimal(0),
            monthly_savings_eur=savings,
            monthly_savings_source=source,
            annual_return_pct=annual_return_pct,
            return_low_pct=low_pct,
            return_high_pct=high_pct,
            annual_inflation_pct=annual_inflation_pct,
            real=real,
            points=[],
        )

    months = years * 12
    series = {
        key: project_wealth(row.value_eur, savings, rate, months)
        for key, rate in (("low", low_pct), ("mid", annual_return_pct), ("high", high_pct))
    }
    if real:
        series = {
            key: deflate_projection(points, annual_inflation_pct)
            for key, points in series.items()
        }

    points = [
        ProjectionPoint(
            date=add_months(row.date, month),
            low_eur=low,
            mid_eur=mid,
            high_eur=high,
        )
        for (month, low), (_, mid), (_, high) in zip(
            series["low"], series["mid"], series["high"]
        )
    ]

    return ProjectionResponse(
        scope=scope,
        start_date=row.date,
        start_value_eur=row.value_eur,
        monthly_savings_eur=savings,
        monthly_savings_source=source,
        annual_return_pct=annual_return_pct,
        return_low_pct=low_pct,
        return_high_pct=high_pct,
        annual_inflation_pct=annual_inflation_pct,
        real=real,
        points=points,
    )
