from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_scope
from app.database import get_db
from app.milestones_service import compute_milestone
from app.schemas import MilestoneResponse

router = APIRouter(prefix="/api/milestones", tags=["milestones"])


@router.get("", response_model=MilestoneResponse)
def get_milestone(
    scope: str = "net",
    assumed_return: Decimal = Query(default=Decimal(5)),
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> MilestoneResponse:
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
