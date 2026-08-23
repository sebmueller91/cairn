from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import audit
from app.auth import get_scope, require_write_scope
from app.database import get_db
from app.models import ImportBatch, Txn, TxnSource
from app.schemas import (
    BulkTransactionsRequest,
    BulkTransactionsResponse,
    ErrorDetail,
    RowResult,
    TransactionCreate,
    TransactionDryRunResult,
    TransactionRead,
    TransactionUpdate,
)
from app.txn_service import (
    TxnValidationError,
    apply_transaction_patch,
    build_txn,
    check_holdings,
    compute_amount_eur,
    payload_hash,
    resolve_fx_rate,
    resolve_price,
    validate_holdings_replay,
    validate_references,
)

router = APIRouter(prefix="/api", tags=["transactions"])


@router.get("/transactions", response_model=list[TransactionRead])
def list_transactions(
    account_id: int | None = None,
    instrument_id: int | None = None,
    # spec 7.1 names these `from`/`to` (see docs/spec.md); `from` isn't a
    # legal Python identifier so it comes in aliased, same pattern as
    # app/routers/timeseries.py's get_networth_timeseries. date_from/date_to
    # keep working too — nothing else in the codebase used them, but there's
    # no reason to break a caller that might.
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    # SQLite treats a negative LIMIT as "unlimited" — without a floor this
    # turned limit=-1 into an accidental full-table dump. 1000 as a
    # ceiling is generous for a single-household ledger and keeps a
    # careless caller from forcing a huge response.
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    _scope=Depends(get_scope),
) -> list[TransactionRead]:
    effective_from = from_ if from_ is not None else date_from
    effective_to = to if to is not None else date_to
    query = db.query(Txn).filter(Txn.voided_at.is_(None))
    if account_id is not None:
        query = query.filter(Txn.account_id == account_id)
    if instrument_id is not None:
        query = query.filter(Txn.instrument_id == instrument_id)
    if effective_from is not None:
        query = query.filter(Txn.date >= effective_from)
    if effective_to is not None:
        query = query.filter(Txn.date <= effective_to)
    rows = query.order_by(Txn.date.desc(), Txn.id.desc()).limit(limit).all()
    return [TransactionRead.model_validate(r) for r in rows]


def _process_row(db: Session, row: TransactionCreate, import_batch_id: int) -> RowResult:
    existing = db.query(Txn).filter(Txn.external_id == row.external_id).first()
    if existing is not None:
        if existing.payload_hash == payload_hash(row):
            return RowResult(
                external_id=row.external_id,
                outcome="duplicate_skipped",
                transaction=TransactionRead.model_validate(existing),
            )
        return RowResult(
            external_id=row.external_id,
            outcome="error",
            error=ErrorDetail(
                code="external_id_conflict",
                params={"external_id": row.external_id},
            ),
        )

    try:
        validate_references(db, row)
        fx_rate = resolve_fx_rate(db, row)
        price = resolve_price(db, row)
        amount_eur = compute_amount_eur(row, fx_rate, price)
        check_holdings(db, row)
    except TxnValidationError as e:
        return RowResult(
            external_id=row.external_id,
            outcome="error",
            error=ErrorDetail(code=e.code, params=e.params),
        )

    txn = build_txn(row, import_batch_id, amount_eur, fx_rate, price)
    db.add(txn)
    db.flush()  # assigns txn.id, makes it visible to subsequent rows' checks
    audit.record(
        db,
        actor=row.source,
        action="create",
        entity="txn",
        entity_id=txn.id,
        payload_hash=txn.payload_hash,
    )
    return RowResult(
        external_id=row.external_id,
        outcome="created",  # relabelled to would_create below if dry_run
        transaction=TransactionRead.model_validate(txn),
    )


@router.post(
    "/transactions/bulk",
    response_model=BulkTransactionsResponse,
)
def bulk_transactions(
    body: BulkTransactionsRequest,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> BulkTransactionsResponse:
    source = body.transactions[0].source if body.transactions else None
    import_batch = ImportBatch(label=body.import_batch_label, source=source)
    db.add(import_batch)
    db.flush()

    results = [_process_row(db, row, import_batch.id) for row in body.transactions]

    if body.dry_run:
        for result in results:
            if result.outcome == "created":
                result.outcome = "would_create"
        db.rollback()
        return BulkTransactionsResponse(dry_run=True, import_batch_id=None, rows=results)

    db.commit()
    return BulkTransactionsResponse(
        dry_run=False, import_batch_id=import_batch.id, rows=results
    )


@router.post(
    "/transactions", response_model=TransactionRead, status_code=status.HTTP_201_CREATED
)
def create_transaction(
    body: TransactionCreate,
    # Mirrors /transactions/bulk's dry_run: run the full validation
    # pipeline, then roll back instead of committing. A query param rather
    # than a body field — TransactionCreate is also embedded as each row of
    # BulkTransactionsRequest.transactions, and a per-row dry_run there
    # would be meaningless (the batch's own dry_run governs all rows), so
    # it doesn't belong on that schema.
    dry_run: bool = False,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> TransactionRead | JSONResponse:
    existing = db.query(Txn).filter(Txn.external_id == body.external_id).first()
    if existing is not None:
        if existing.payload_hash == payload_hash(body):
            return TransactionRead.model_validate(existing)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "external_id_conflict",
                "params": {"external_id": body.external_id},
            },
        )

    try:
        validate_references(db, body)
        fx_rate = resolve_fx_rate(db, body)
        price = resolve_price(db, body)
        amount_eur = compute_amount_eur(body, fx_rate, price)
        check_holdings(db, body)
    except TxnValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": e.code, "params": e.params},
        )

    import_batch = ImportBatch(label=None, source=body.source)
    db.add(import_batch)
    db.flush()
    txn = build_txn(body, import_batch.id, amount_eur, fx_rate, price)
    db.add(txn)
    db.flush()  # assigns txn.id, needed for the audit record and the response
    audit.record(
        db,
        actor=body.source,
        action="create",
        entity="txn",
        entity_id=txn.id,
        payload_hash=txn.payload_hash,
    )

    if dry_run:
        # Capture the would-be transaction as plain data *before* rolling
        # back — db.rollback() expires every object still attached to the
        # session, so reading txn's attributes afterwards would silently
        # re-query (or blow up, since none of this was ever committed).
        result = TransactionDryRunResult(
            outcome="would_create",
            transaction=TransactionRead.model_validate(txn),
        )
        db.rollback()
        # A Response instance bypasses response_model entirely (FastAPI
        # sends it through as-is), so this never gets coerced into
        # TransactionRead / status 201 — a dry run must be structurally
        # impossible to mistake for a real booking.
        return JSONResponse(
            status_code=status.HTTP_200_OK, content=result.model_dump(mode="json")
        )

    db.commit()
    db.refresh(txn)
    return TransactionRead.model_validate(txn)


def _get_txn_or_404(db: Session, txn_id: int) -> Txn:
    txn = db.get(Txn, txn_id)
    if txn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "transaction_not_found", "params": {"id": txn_id}},
        )
    return txn


@router.patch("/transactions/{txn_id}", response_model=TransactionRead)
def update_transaction(
    txn_id: int,
    body: TransactionUpdate,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> TransactionRead:
    txn = _get_txn_or_404(db, txn_id)
    before = {
        "date": str(txn.date),
        "quantity": str(txn.quantity) if txn.quantity is not None else None,
        "price": str(txn.price) if txn.price is not None else None,
        "fees": str(txn.fees),
        "tax": str(txn.tax),
        "note": txn.note,
        "provisional": txn.provisional,
    }
    updates = body.model_dump(exclude_unset=True, mode="json")
    changed_fields = set(body.model_dump(exclude_unset=True).keys())
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(txn, field, value)

    try:
        # Recomputes amount_eur when a patched field feeds it (the only
        # field the ledger reads for cost), re-runs the same validation
        # the create path runs (including the future-date check a plain
        # setattr loop bypasses), and confirms the edit hasn't starved a
        # later SELL/TRANSFER for the same instrument.
        apply_transaction_patch(db, txn, changed_fields)
    except TxnValidationError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": e.code, "params": e.params},
        )

    audit.record(
        db,
        actor=TxnSource.AGENT,
        action="update",
        entity="txn",
        entity_id=txn.id,
        payload_hash=txn.payload_hash,
        diff={"before": before, "after": updates},
    )
    db.commit()
    db.refresh(txn)
    return TransactionRead.model_validate(txn)


@router.delete("/transactions/{txn_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(
    txn_id: int,
    db: Session = Depends(get_db),
    _scope=Depends(require_write_scope),
) -> None:
    txn = _get_txn_or_404(db, txn_id)
    batch_id = txn.import_batch_id
    instrument_id = txn.instrument_id
    txn_id_value = txn.id
    txn_payload_hash = txn.payload_hash

    db.delete(txn)
    db.flush()

    # A hard delete of e.g. a BUY can starve a later SELL/TRANSFER for the
    # same instrument, which would otherwise leave the ledger unreplayable
    # (500s on every read endpoint from then on) — replay before
    # committing and reject the delete if it breaks the history.
    if instrument_id is not None:
        try:
            validate_holdings_replay(db, instrument_id, "delete_breaks_holdings")
        except TxnValidationError as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": e.code, "params": e.params},
            )

    audit.record(
        db,
        actor=TxnSource.AGENT,
        action="delete",
        entity="txn",
        entity_id=txn_id_value,
        payload_hash=txn_payload_hash,
    )
    # A batch left with zero transactions (the common case: single manual
    # entries each get their own batch of one, per docs/data-model.md
    # invariant 4) is just clutter — remove it rather than let empty
    # batches accumulate.
    remaining = db.query(Txn).filter(Txn.import_batch_id == batch_id).first()
    if remaining is None:
        batch = db.get(ImportBatch, batch_id)
        if batch is not None:
            db.delete(batch)
    db.commit()
