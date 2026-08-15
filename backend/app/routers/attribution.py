from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.attribution_service import attribution_series
from app.auth import get_scope
from app.database import get_db
from app.models import DailySnapshot
from app.schemas import AttributionPeriod, AttributionResponse

router = APIRouter(prefix="/api/attribution", tags=["attribution"])


@router.get("", response_model=AttributionResponse)
def get_attribution(
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    granularity: str = "month",
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> AttributionResponse:
    if granularity not in ("month", "year"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_granularity", "params": {"granularity": granularity}},
        )

    end = to or date.today()
    start = from_
    if start is None:
        earliest = (
            db.query(DailySnapshot.date)
            .filter(DailySnapshot.scope_type == "total", DailySnapshot.scope_id == "gross")
            .order_by(DailySnapshot.date)
            .first()
        )
        start = earliest[0] if earliest else end

    if start > end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_range", "params": {"from": str(start), "to": str(end)}},
        )

    buckets = attribution_series(db, start, end, granularity)
    return AttributionResponse(
        granularity=granularity,
        periods=[
            AttributionPeriod(
                start_date=b.start_date,
                end_date=b.end_date,
                start_value=b.start_value,
                end_value=b.end_value,
                deposits_withdrawals=b.deposits_withdrawals,
                income=b.income,
                costs=b.costs,
                valuation_adjustments=b.valuation_adjustments,
                fx_effect=b.fx_effect,
                market_gains_losses=b.market_gains_losses,
            )
            for b in buckets
        ],
    )
