from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_scope
from app.contributions_service import compute_contributions
from app.database import get_db
from app.schemas import ContributionsResponse

router = APIRouter(prefix="/api/contributions", tags=["contributions"])


@router.get("", response_model=ContributionsResponse)
def get_contributions(
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> ContributionsResponse:
    """Money put in per asset class, principal repaid and net-worth change
    over a window. Defaults to the trailing 12 months."""
    end = to or date.today()
    start = from_ or (end - timedelta(days=365))
    data = compute_contributions(db, start, end)
    return ContributionsResponse(
        start_date=data.start_date,
        end_date=data.end_date,
        by_asset_class={k: v for k, v in data.by_asset_class.items()},
        total_invested=data.total_invested,
        debt_repaid=data.debt_repaid,
        net_worth_change=data.net_worth_change,
    )
