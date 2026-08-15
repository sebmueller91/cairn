from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.allocation_service import (
    compute_drift,
    current_allocation,
    full_rebalance_proposal,
    get_targets,
    purchases_only_proposal,
    set_targets,
)
from app.auth import get_scope, require_write_scope
from app.database import get_db
from app.schemas import (
    AllocationResponse,
    DriftRowRead,
    RebalanceProposalRead,
    TargetAllocationUpdate,
)

router = APIRouter(prefix="/api/allocation", tags=["allocation"])


@router.get("/targets", response_model=dict[str, Decimal])
def get_target_allocation(
    db: Session = Depends(get_db), _scope=Depends(get_scope)
) -> dict[str, Decimal]:
    return get_targets(db)


@router.put("/targets", response_model=dict[str, Decimal])
def put_target_allocation(
    body: TargetAllocationUpdate,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> dict[str, Decimal]:
    try:
        set_targets(db, body.targets)
    except ValueError:
        total = sum(body.targets.values(), Decimal(0))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "targets_must_sum_to_100", "params": {"sum": str(total)}},
        ) from None
    db.commit()
    return get_targets(db)


@router.get("", response_model=AllocationResponse)
def get_allocation(
    contribution: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> AllocationResponse:
    targets = get_targets(db)
    current = current_allocation(db)
    drift = compute_drift(current, targets)

    rebalance_purchases_only = None
    if contribution is not None:
        try:
            contribution_amount = Decimal(contribution)
        except InvalidOperation:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "invalid_contribution", "params": {"contribution": contribution}},
            ) from None
        rebalance_purchases_only = [
            RebalanceProposalRead(asset_class=p.asset_class, amount_eur=p.amount)
            for p in purchases_only_proposal(drift, contribution_amount)
        ]

    return AllocationResponse(
        drift=[
            DriftRowRead(
                asset_class=row.asset_class,
                current_value_eur=row.current_value,
                current_pct=row.current_pct,
                target_pct=row.target_pct,
                drift_pp=row.drift_pp,
                drift_value_eur=row.drift_value,
            )
            for row in drift
        ],
        rebalance_full=[
            RebalanceProposalRead(asset_class=p.asset_class, amount_eur=p.amount)
            for p in full_rebalance_proposal(drift)
        ],
        rebalance_purchases_only=rebalance_purchases_only,
    )
