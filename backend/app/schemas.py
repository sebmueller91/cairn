from decimal import Decimal

# Aliased: several models below have a field literally named `date`
# (txn.date). Pydantic resolves annotation strings using each class's own
# namespace, so a bare `date | None` there would resolve to the class's
# own `date` attribute (its default value) instead of this type — a real
# shadowing bug, not a style preference. Importing under a different name
# sidesteps it everywhere, not just where it would currently bite.
from datetime import date as date_, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.models import (
    AccountType,
    AssetClass,
    DatePrecision,
    LiquidityTier,
    PriceMode,
    TransactionType,
    TxnSource,
    ValuationMode,
)

# Pydantic serializes Decimal to a bare JSON number by default, which a
# client parsing with JSON.parse silently turns back into a float — exactly
# the imprecision the backend goes out of its way to avoid. Serializing as
# a string forces every client to make an explicit choice about how to
# parse it, instead of getting a float for free.
DecimalStr = Annotated[
    Decimal, PlainSerializer(lambda v: str(v), return_type=str, when_used="json")
]


class AccountCreate(BaseModel):
    name: str = Field(min_length=1)
    type: AccountType
    currency: str = Field(min_length=3, max_length=3)
    institution: str | None = None
    opened_at: date_ | None = None
    verified_from: date_ | None = None
    sort_order: int = 0


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    institution: str | None = None
    opened_at: date_ | None = None
    closed_at: date_ | None = None
    verified_from: date_ | None = None
    sort_order: int | None = None
    archived: bool | None = None


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: AccountType
    currency: str
    institution: str | None
    opened_at: date_ | None
    closed_at: date_ | None
    verified_from: date_ | None
    sort_order: int
    archived: bool
    created_at: datetime
    updated_at: datetime


class InstrumentCreate(BaseModel):
    name: str = Field(min_length=1)
    isin: str | None = Field(default=None, min_length=12, max_length=12)
    wkn: str | None = None
    ticker: str | None = None
    asset_class: AssetClass
    valuation_mode: ValuationMode
    currency: str = Field(min_length=3, max_length=3)
    region: str | None = None
    sector: str | None = None
    liquidity_tier: LiquidityTier | None = None
    ter_pct: DecimalStr | None = None
    fine_weight_g: DecimalStr | None = None
    valuation_config: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None


class InstrumentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    ticker: str | None = None
    region: str | None = None
    sector: str | None = None
    liquidity_tier: LiquidityTier | None = None
    ter_pct: DecimalStr | None = None
    fine_weight_g: DecimalStr | None = None
    valuation_config: dict | None = None
    tags: list[str] | None = None
    notes: str | None = None


class InstrumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    isin: str | None
    wkn: str | None
    ticker: str | None
    asset_class: AssetClass
    valuation_mode: ValuationMode
    currency: str
    region: str | None
    sector: str | None
    liquidity_tier: LiquidityTier | None
    ter_pct: DecimalStr | None
    fine_weight_g: DecimalStr | None
    valuation_config: dict
    tags: list[str]
    notes: str | None
    created_at: datetime
    updated_at: datetime


# Types requiring a Loan or valuation_anchor table (phase 5, not built yet)
# are deliberately not accepted by the phase-1 transactions endpoint.
UNSUPPORTED_TXN_TYPES = {
    TransactionType.VALUATION,
    TransactionType.LOAN_PAYMENT,
    TransactionType.EXTRA_REPAYMENT,
}


class TransactionCreate(BaseModel):
    external_id: str = Field(min_length=1)
    date: date_
    date_precision: DatePrecision = DatePrecision.DAY
    type: TransactionType
    account_id: int
    instrument_id: int | None = None
    counter_account_id: int | None = None
    quantity: DecimalStr | None = None
    price: DecimalStr | None = None
    price_mode: PriceMode = PriceMode.EXACT
    # Native-currency flow amount for types that aren't quantity*price
    # (DIVIDEND, FEE, DEPOSIT, ...) — see app/txn_service.py for exactly
    # which types need which fields.
    amount: DecimalStr | None = None
    currency: str = Field(min_length=3, max_length=3)
    fx_rate: DecimalStr | None = None
    fees: DecimalStr = Decimal(0)
    tax: DecimalStr = Decimal(0)
    split_ratio: DecimalStr | None = None
    provisional: bool = False
    note: str | None = None
    source: TxnSource = TxnSource.AGENT


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    import_batch_id: int
    date: date_
    date_precision: DatePrecision
    type: TransactionType
    account_id: int
    instrument_id: int | None
    counter_account_id: int | None
    quantity: DecimalStr | None
    price: DecimalStr | None
    price_mode: PriceMode
    currency: str
    fx_rate: DecimalStr | None
    fees: DecimalStr
    tax: DecimalStr
    amount_eur: DecimalStr
    provisional: bool
    voided_at: datetime | None
    voided_by_batch_id: int | None
    note: str | None
    source: TxnSource
    created_at: datetime
    updated_at: datetime


class TransactionUpdate(BaseModel):
    date: date_ | None = None
    date_precision: DatePrecision | None = None
    quantity: DecimalStr | None = None
    price: DecimalStr | None = None
    fees: DecimalStr | None = None
    tax: DecimalStr | None = None
    note: str | None = None
    provisional: bool | None = None


class BulkTransactionsRequest(BaseModel):
    dry_run: bool = True
    import_batch_label: str | None = None
    transactions: list[TransactionCreate]


class RowResult(BaseModel):
    external_id: str
    outcome: str  # would_create | duplicate_skipped | created | error
    transaction: TransactionRead | None = None
    error: "ErrorDetail | None" = None


class BulkTransactionsResponse(BaseModel):
    dry_run: bool
    import_batch_id: int | None = None
    rows: list[RowResult]


class PositionRead(BaseModel):
    account_id: int | None
    instrument_id: int
    quantity: DecimalStr
    cost_basis_eur: DecimalStr
    realized_pl_eur: DecimalStr


class ErrorDetail(BaseModel):
    code: str
    params: dict = {}
