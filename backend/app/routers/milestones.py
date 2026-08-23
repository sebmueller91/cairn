from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import get_scope
from app.database import get_db
from app.milestones_service import compute_milestone
from app.schemas import MilestoneResponse

router = APIRouter(prefix="/api/milestones", tags=["milestones"])

# Mirrors the three scope_id values snapshot_service.py writes for
# scope_type="total" — same set /api/timeseries/networth validates against.
# An unrecognized scope used to silently read as a snapshot with no rows,
# reporting a 0 current_value_eur milestone instead of rejecting the request.
VALID_SCOPES = ("investable", "gross", "net")


@router.get("", response_model=MilestoneResponse)
def get_milestone(
    scope: str = "net",
    assumed_return: Decimal = Query(default=Decimal(5)),
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> MilestoneResponse:
    if scope not in VALID_SCOPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_scope", "params": {"scope": scope}},
        )
    result = compute_milestone(db, scope=scope, assumed_annual_return_pct=assumed_return)
    return MilestoneResponse(
        scope=result.scope,
        current_value_eur=result.current_value_eur,
        next_milestone_eur=result.next_milestone_eur,
        monthly_savings_eur=result.monthly_savings_eur,
        assumed_annual_return_pct=result.assumed_annual_return_pct,
        months_to_reach=result.months_to_reach,
        estimated_date=result.estimated_date,
    )
