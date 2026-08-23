import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.ledger import InsufficientHoldingError
from app.routers import (
    accounts,
    admin,
    allocation,
    attribution,
    auth,
    contributions,
    cpi,
    data_quality,
    export,
    health,
    house_index,
    import_batches,
    instruments,
    loans,
    look_through,
    milestones,
    performance,
    positions,
    price_sources,
    prices,
    reconcile,
    tax,
    timeseries,
    transactions,
    valuations,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Unconditionally, and before anything else: uvicorn's LOGGING_CONFIG
    # only configures its own `uvicorn*` loggers and leaves root at WARNING
    # with no handler, so without this every `logger.info` under `app.*` is
    # dropped — including the one line that says the nightly jobs ran. Not
    # gated on enable_scheduler: the request path logs too.
    from app.scheduler import configure_app_logging

    configure_app_logging()

    scheduler = None
    if get_settings().enable_scheduler:
        from app.scheduler import create_scheduler

        scheduler = create_scheduler()
        scheduler.start()
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="Cairn API",
    description="Self-hosted net worth and portfolio tracker.",
    version="0.1.0",
    lifespan=lifespan,
)

logger = logging.getLogger("cairn")

# Every hand-raised HTTPException in this codebase already carries
# detail={"code": ..., "params": {...}} (AGENTS.md: "API errors return
# machine-readable codes"), and FastAPI's default HTTPException handler
# wraps that in {"detail": ...} on the wire — frontend/src/lib/api.ts reads
# body.detail.code. The two handlers below extend that same wire shape to
# the two paths that used to leak past it entirely: FastAPI's own
# RequestValidationError (a list of pydantic error dicts, e.g. a German
# "2000,50" typed into a Decimal query param) and any other unhandled
# exception (a bare-text 500 that response.json() chokes on).

# pydantic-core error "type" -> a stable, translatable code. Deliberately
# coarse (a handful of buckets) rather than one code per pydantic internal
# type string, since pydantic's exact type names are not a public/stable
# API and the frontend only needs to know *what kind* of thing was wrong.
_VALIDATION_TYPE_CODES = {
    "decimal_parsing": "invalid_decimal",
    "int_parsing": "invalid_integer",
    "int_type": "invalid_integer",
    "float_parsing": "invalid_number",
    "float_type": "invalid_number",
    "date_parsing": "invalid_date",
    "date_from_datetime_parsing": "invalid_date",
    "datetime_parsing": "invalid_date",
    "bool_parsing": "invalid_boolean",
    "bool_type": "invalid_boolean",
    "missing": "missing_param",
    "string_too_short": "value_too_short",
    "string_too_long": "value_too_long",
    "string_type": "invalid_value",
    "enum": "invalid_choice",
    "literal_error": "invalid_choice",
    "json_invalid": "invalid_json",
}


def _field_path(loc: tuple) -> str | None:
    """loc[0] is always the location ("query"/"path"/"body"/"header"); the
    rest is the field, possibly nested (["body", "transactions", 0,
    "external_id"]) for a bulk-request row. Joined with "." (list indices
    included) so the frontend can point at the exact offending field
    without the backend having to know the field's display label."""
    if len(loc) <= 1:
        return str(loc[0]) if loc else None
    return ".".join(str(part) for part in loc[1:])


def _validation_error_code(error: dict) -> tuple[str, dict]:
    err_type = error.get("type", "value_error")
    loc = tuple(error.get("loc", ()))
    code = _VALIDATION_TYPE_CODES.get(err_type, "invalid_value")
    params: dict = {
        "field": _field_path(loc),
        "location": loc[0] if loc else None,
    }
    if "input" in error and error["input"] is not None:
        # Stringified deliberately: the input can be arbitrary JSON (a
        # dict, a list) and params must stay JSON-serializable without
        # the frontend having to branch on its shape.
        params["value"] = str(error["input"])
    return code, params


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = exc.errors()
    # Full pydantic detail (including any raw input) goes to the log only —
    # AGENTS.md/the bug report: never leak internal exception detail into
    # the response body, but it's exactly what's needed to diagnose a
    # report of "this field rejected valid input".
    logger.info("Validation error on %s %s: %s", request.method, request.url.path, errors)
    if not errors:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": {"code": "invalid_request", "params": {}}},
        )
    code, params = _validation_error_code(errors[0])
    if len(errors) > 1:
        params["error_count"] = len(errors)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": {"code": code, "params": params}},
    )


@app.exception_handler(InsufficientHoldingError)
async def insufficient_holding_handler(
    request: Request, exc: InsufficientHoldingError
) -> JSONResponse:
    # The write paths now refuse to create an unreplayable ledger, but a
    # database poisoned *before* those guards existed — by the old PATCH,
    # DELETE or batch rollback — still raises this on every read that
    # replays the ledger (positions, tax, look-through, data-quality, the
    # nightly rebuild). Guarding writes does not heal existing data.
    #
    # Without this, all of those are an opaque 500 and the operator has no
    # way to know which row to correct. Naming the account, instrument and
    # the shortfall turns "the app is broken" into "this sale is larger
    # than the holding it draws on".
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": {
                "code": "ledger_unreplayable",
                "params": {
                    "account_id": exc.account_id,
                    "instrument_id": exc.instrument_id,
                    "requested": str(exc.requested),
                    "available": str(exc.available),
                },
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Full traceback to the log, never to the client — the previous
    # behaviour was a plain-text "Internal Server Error" body anyway, which
    # already told a client nothing; this just makes the failure visible to
    # whoever runs the Pi instead of dropping it on the floor.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": {"code": "internal_error", "params": {}}},
    )


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(instruments.router)
app.include_router(price_sources.router)
app.include_router(prices.router)
app.include_router(transactions.router)
app.include_router(positions.router)
app.include_router(import_batches.router)
app.include_router(admin.router)
app.include_router(timeseries.router)
app.include_router(reconcile.router)
app.include_router(valuations.router)
app.include_router(house_index.router)
app.include_router(cpi.router)
app.include_router(data_quality.router)
app.include_router(export.router)
app.include_router(loans.router)
app.include_router(performance.router)
app.include_router(attribution.router)
app.include_router(contributions.router)
app.include_router(allocation.router)
app.include_router(tax.router)
app.include_router(look_through.router)
app.include_router(milestones.router)
