from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import get_scope
from app.database import get_db
from app.schemas import (
    LiquidationSummaryRead,
    PrivateSaleAllowanceUsage,
    SaverAllowanceUsage,
    TaxOverviewResponse,
    UnrealizedTaxEstimateRead,
    VorabpauschaleEntryRead,
)
from app.tax_service import (
    DEFAULT_PERSONAL_INCOME_TAX_RATE,
    DEFAULT_PRIVATE_SALE_EXEMPTION_LIMIT_EUR,
    liquidation_summary,
    private_sale_allowance_usage,
    saver_allowance_usage,
    vorabpauschale_for,
    vorabpauschale_reminder,
)

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
    allowance: Decimal = Query(default=DEFAULT_ALLOWANCE_EUR, ge=0),
    # The §23 leg is taxed at the personal marginal rate, which is
    # per-person by definition and so cannot be a server constant.
    personal_tax_rate: Decimal = Query(
        default=DEFAULT_PERSONAL_INCOME_TAX_RATE, ge=0, le=1
    ),
    private_sale_limit: Decimal = Query(
        default=DEFAULT_PRIVATE_SALE_EXEMPTION_LIMIT_EUR, ge=0
    ),
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
    private = private_sale_allowance_usage(db, resolved_year, private_sale_limit)
    summary = liquidation_summary(
        db,
        remaining_allowance_eur=max(usage.remaining_eur, Decimal(0)),
        private_sale_realized_taxable_eur=private.realized_taxable_eur,
        personal_tax_rate=personal_tax_rate,
        private_sale_exemption_limit_eur=private_sale_limit,
    )

    return TaxOverviewResponse(
        saver_allowance=SaverAllowanceUsage.model_validate(usage),
        private_sale_allowance=PrivateSaleAllowanceUsage.model_validate(private),
        liquidation=LiquidationSummaryRead.model_validate(summary),
        unrealized=[UnrealizedTaxEstimateRead.model_validate(row) for row in summary.rows],
        vorabpauschale=(
            VorabpauschaleEntryRead.model_validate(entry)
            if (entry := vorabpauschale_for(db, resolved_year))
            else None
        ),
        vorabpauschale_reminder=vorabpauschale_reminder(db),
    )
