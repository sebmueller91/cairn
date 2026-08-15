from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_scope, require_write_scope
from app.database import get_db
from app.models import Account, Loan, Txn
from app.schemas import AccountCreate, AccountRead, AccountUpdate

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def _get_or_404(db: Session, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "account_not_found", "params": {"id": account_id}},
        )
    return account


@router.post("", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
def create_account(
    body: AccountCreate,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> Account:
    account = Account(**body.model_dump())
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get("", response_model=list[AccountRead])
def list_accounts(
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> list[Account]:
    return list(db.query(Account).order_by(Account.sort_order, Account.id).all())


@router.get("/{account_id}", response_model=AccountRead)
def get_account(
    account_id: int,
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> Account:
    return _get_or_404(db, account_id)


@router.patch("/{account_id}", response_model=AccountRead)
def update_account(
    account_id: int,
    body: AccountUpdate,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> Account:
    account = _get_or_404(db, account_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(account, field, value)
    db.commit()
    db.refresh(account)
    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    account_id: int,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> None:
    account = _get_or_404(db, account_id)
    has_txns = (
        db.query(Txn)
        .filter(
            (Txn.account_id == account_id) | (Txn.counter_account_id == account_id)
        )
        .first()
        is not None
    )
    if has_txns:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "account_has_transactions",
                "params": {"account_id": account_id},
            },
        )
    # A loan is real financial configuration (principal, rate, schedule),
    # not disposable cache like a price_source — block like transactions
    # rather than silently cascading it away. Found live: this FK was
    # added in phase 5 and this guard wasn't updated for it, so deleting
    # a LOAN-type account crashed the same way instrument delete once did.
    has_loan = db.query(Loan).filter(Loan.account_id == account_id).first() is not None
    if has_loan:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "account_has_loan", "params": {"account_id": account_id}},
        )
    db.delete(account)
    db.commit()
