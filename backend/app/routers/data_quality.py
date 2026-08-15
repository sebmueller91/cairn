from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_scope
from app.data_quality_service import check_data_quality
from app.database import get_db
from app.schemas import DataQualityIssueRead, DataQualityResponse

router = APIRouter(prefix="/api/data-quality", tags=["data-quality"])


@router.get("", response_model=DataQualityResponse)
def get_data_quality(
    db: Session = Depends(get_db), _scope=Depends(get_scope)
) -> DataQualityResponse:
    issues = check_data_quality(db)
    return DataQualityResponse(
        issues=[
            DataQualityIssueRead(
                kind=i.kind,
                instrument_id=i.instrument_id,
                instrument_name=i.instrument_name,
                account_id=i.account_id,
                detail=i.detail,
                age_days=i.age_days,
            )
            for i in issues
        ]
    )
