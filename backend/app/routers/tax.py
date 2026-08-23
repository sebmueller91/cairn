from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import get_scope
from app.database import get_db
from app.schemas import SaverAllowanceUsage, TaxOverviewResponse, UnrealizedTaxEstimateRead
from app.tax_service import saver_allowance_usage, unrealized_tax_estimates, vorabpauschale_reminder

router = APIRouter(prefix="/api/tax", tags=["tax"])

# Germany's Sparerpauschbetrag for a single filer as of recent years —
# illustrative default, not authoritative (spec 4.6: non-binding), and
# overridable per request since it changes with tax law and filing status
# (married filing jointly gets double).
DEFAULT_ALLOWANCE_EUR = Decimal("1000")

# Python's date() supports years 1..9999 (MINYEAR/MAXYEAR) — anything
# outside that blows up saver_allowance_usage's date(year, 1, 1) with an
# unhandled ValueError (a 500), not a rejection of a bad request.
MIN_YEAR = 1
MAX_YEAR = 9999


@router.get("", response_model=TaxOverviewResponse)
def get_tax_overview(
    year: int | None = Query(default=None),
    allowance: Decimal = Query(default=DEFAULT_ALLOWANCE_EUR),
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> TaxOverviewResponse:
    # `year or date.today().year` treated 0 as falsy and silently fell back
    # to the current year — an explicit None-check is required so
    # year=0 (out of range, handled below) doesn't get silently swallowed.
    resolved_year = year if year is not None else date.today().year
    if not (MIN_YEAR <= resolved_year <= MAX_YEAR):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_year",
                "params": {"year": resolved_year, "min": MIN_YEAR, "max": MAX_YEAR},
            },
        )
    usage = saver_allowance_usage(db, resolved_year, allowance)
    remaining = max(usage["remaining_eur"], Decimal(0))
    unrealized = unrealized_tax_estimates(db, remaining_allowance_eur=remaining)
    reminder = vorabpauschale_reminder(db)

    return TaxOverviewResponse(
        saver_allowance=SaverAllowanceUsage(**usage),
        unrealized=[
            UnrealizedTaxEstimateRead(
                account_id=row.account_id,
                instrument_id=row.instrument_id,
                quantity=row.quantity,
                cost_basis_eur=row.cost_basis_eur,
                current_value_eur=row.current_value_eur,
                unrealized_pl_eur=row.unrealized_pl_eur,
                estimated_tax_eur=row.estimated_tax_eur,
            )
            for row in unrealized
        ],
        vorabpauschale_reminder=reminder,
    )
