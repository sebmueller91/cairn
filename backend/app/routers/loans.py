from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import audit
from app.auth import get_scope, require_write_scope
from app.database import get_db
from app.db_types import quantize_money
from app.loan_service import LoanConfig, loan_balance, loan_to_value
from app.models import Account, AccountType, Loan, TransactionType, Txn, TxnSource
from app.schemas import LoanCreate, LoanRead, LoanStatus, LoanUpdate
from app.valuation_service import current_instrument_value

router = APIRouter(prefix="/api/loans", tags=["loans"])


@router.post("", response_model=LoanRead, status_code=status.HTTP_201_CREATED)
def create_loan(
    body: LoanCreate,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> Loan:
    account = db.get(Account, body.account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "account_not_found", "params": {"id": body.account_id}},
        )
    if account.type != AccountType.LOAN:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "not_a_loan_account", "params": {"account_id": body.account_id}},
        )
    loan = Loan(**body.model_dump())
    db.add(loan)
    db.flush()  # assigns loan.id, needed for the audit record
    # This router has no source field to distinguish agent vs. manual UI
    # use — both arrive over the same bearer/cookie auth — so every write
    # here is logged as TxnSource.AGENT, same as transactions.py's
    # PATCH/DELETE.
    audit.record(
        db,
        actor=TxnSource.AGENT,
        action="create",
        entity="loan",
        entity_id=loan.id,
        payload_hash="n/a",
    )
    db.commit()
    db.refresh(loan)
    return loan


@router.get("", response_model=list[LoanRead])
def list_loans(db: Session = Depends(get_db), _scope=Depends(get_scope)) -> list[Loan]:
    return db.query(Loan).all()


def _get_or_404(db: Session, loan_id: int) -> Loan:
    loan = db.get(Loan, loan_id)
    if loan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "loan_not_found", "params": {"id": loan_id}},
        )
    return loan


@router.get("/{loan_id}", response_model=LoanRead)
def get_loan(
    loan_id: int, db: Session = Depends(get_db), _scope=Depends(get_scope)
) -> Loan:
    return _get_or_404(db, loan_id)


@router.patch("/{loan_id}", response_model=LoanRead)
def update_loan(
    loan_id: int,
    body: LoanUpdate,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> Loan:
    loan = _get_or_404(db, loan_id)
    before = {
        "principal": str(loan.principal),
        "rate_pct": str(loan.rate_pct),
        "start_date": str(loan.start_date),
        "fixed_until": str(loan.fixed_until) if loan.fixed_until else None,
        "monthly_payment": str(loan.monthly_payment),
        "payment_day": loan.payment_day,
        "extra_repayment_allowance_pct": (
            str(loan.extra_repayment_allowance_pct)
            if loan.extra_repayment_allowance_pct is not None
            else None
        ),
    }
    updates = body.model_dump(exclude_unset=True, mode="json")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(loan, field, value)
    audit.record(
        db,
        actor=TxnSource.AGENT,
        action="update",
        entity="loan",
        entity_id=loan.id,
        payload_hash="n/a",
        diff={"before": before, "after": updates},
    )
    db.commit()
    db.refresh(loan)
    return loan


@router.delete("/{loan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_loan(
    loan_id: int,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> None:
    loan = _get_or_404(db, loan_id)
    audit.record(
        db,
        actor=TxnSource.AGENT,
        action="delete",
        entity="loan",
        entity_id=loan.id,
        payload_hash="n/a",
        diff={"deleted": {"account_id": loan.account_id, "principal": str(loan.principal)}},
    )
    db.delete(loan)
    db.commit()


@router.get("/{loan_id}/status", response_model=LoanStatus)
def get_loan_status(
    loan_id: int,
    as_of: date_type | None = None,
    house_instrument_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> LoanStatus:
    loan = _get_or_404(db, loan_id)
    as_of = as_of or date_type.today()

    extra_repayments = [
        (t.date, t.amount_eur)
        for t in db.query(Txn)
        .filter(
            Txn.account_id == loan.account_id,
            Txn.type == TransactionType.EXTRA_REPAYMENT,
            Txn.voided_at.is_(None),
        )
        .all()
    ]
    config = LoanConfig(
        principal=loan.principal,
        annual_rate_pct=loan.rate_pct,
        start_date=loan.start_date,
        monthly_payment=loan.monthly_payment,
        extra_repayments=extra_repayments,
    )
    balance = quantize_money(loan_balance(config, as_of))

    house_value_eur = None
    ltv = None
    if house_instrument_id is not None:
        raw_house_value = current_instrument_value(db, house_instrument_id, as_of)
        if raw_house_value is not None:
            house_value_eur = quantize_money(raw_house_value)
            ltv = loan_to_value(balance, house_value_eur)

    return LoanStatus(
        loan=loan, balance_eur=balance, ltv=ltv, house_value_eur=house_value_eur
    )
