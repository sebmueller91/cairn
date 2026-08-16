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


# VALUATION stays excluded permanently: POST /api/valuations +
# valuation_anchor is the real mechanism (spec ch. 9's own table sketch
# already treats anchors as a separate resource, not a txn), so a
# VALUATION-type transaction row would just be a second, redundant path
# to the same data. LOAN_PAYMENT/EXTRA_REPAYMENT were phase-5-gated on the
# `loan` table existing — it does now.
UNSUPPORTED_TXN_TYPES = {
    TransactionType.VALUATION,
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


class TransactionDryRunResult(BaseModel):
    """Response for POST /api/transactions?dry_run=true. Deliberately not
    a bare TransactionRead — same envelope shape as a /bulk row (`dry_run`
    + `outcome`) so a client can never mistake this for a real booking."""

    dry_run: bool = True
    outcome: str  # would_create
    transaction: TransactionRead


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
    value_eur: DecimalStr | None = None
    unrealized_pl_eur: DecimalStr | None = None


class SupersedeRequest(BaseModel):
    quantity_tolerance: DecimalStr | None = None
    cost_basis_tolerance_eur: DecimalStr | None = None


class SupersedeDeltaReport(BaseModel):
    account_id: int
    instrument_id: int
    opening_balance_txn_id: int
    original_quantity: DecimalStr
    original_cost_basis_eur: DecimalStr
    recomputed_quantity: DecimalStr
    recomputed_cost_basis_eur: DecimalStr
    matched: bool
    residual_txn_id: int | None = None


class SupersedeResponse(BaseModel):
    reports: list[SupersedeDeltaReport]


class PriceSourceCreate(BaseModel):
    provider: str
    provider_symbol: str = Field(min_length=1)
    priority: int = 0
    enabled: bool = True


class PriceSourceUpdate(BaseModel):
    provider_symbol: str | None = None
    priority: int | None = None
    enabled: bool | None = None


class PriceSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    instrument_id: int
    provider: str
    provider_symbol: str
    priority: int
    enabled: bool
    last_fetch_at: datetime | None
    last_error: str | None


class PriceRefreshRequest(BaseModel):
    instrument_id: int | None = None  # None = every instrument with a price source


class PriceBackfillRequest(BaseModel):
    instrument_id: int
    start: date_ | None = None  # None = as far back as the provider has
    end: date_ | None = None  # None = today


class FxBackfillRequest(BaseModel):
    start: date_
    end: date_ | None = None  # None = today
    # None = every non-EUR currency currently in use by some instrument.
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class FetchResultRead(BaseModel):
    instrument_id: int
    status: str
    detail: str | None = None


class PriceFetchResponse(BaseModel):
    results: list[FetchResultRead]


class NetWorthPoint(BaseModel):
    date: date_
    value_eur: DecimalStr


class AllocationTimeseriesPoint(BaseModel):
    # asset-class name (or CASH/LIABILITY) -> EUR value on this date.
    # Missing keys mean "no rows for that class that day" — the frontend
    # treats an absent key as 0, never a fabricated zero entry here.
    date: date_
    values: dict[str, DecimalStr]


class PerformancePoint(BaseModel):
    date: date_
    index_value: float


class PerformanceResponse(BaseModel):
    scope: str
    period: str
    method: str
    start_date: date_
    end_date: date_
    # TWR: total chained return over the period. MWR: annualised XIRR.
    # None for MWR when the flows didn't converge (e.g. all same-sign,
    # or a degenerate single-flow period) — never a fabricated number.
    return_pct: float | None
    # Only populated for method=twr — a base-100 growth curve for
    # charting. MWR is a single annualised rate, not a curve.
    curve: list[PerformancePoint] | None = None
    # Only populated when a benchmark_instrument_id was requested and the
    # method is twr: "what if every contribution had gone into this
    # instead" (spec 4.2), same base-100 scale as `curve` for a direct
    # chart overlay.
    benchmark_curve: list[PerformancePoint] | None = None


class AttributionPeriod(BaseModel):
    start_date: date_
    end_date: date_
    start_value: DecimalStr
    end_value: DecimalStr
    deposits_withdrawals: DecimalStr
    income: DecimalStr
    costs: DecimalStr
    valuation_adjustments: DecimalStr
    fx_effect: DecimalStr
    market_gains_losses: DecimalStr


class AttributionResponse(BaseModel):
    granularity: str
    periods: list[AttributionPeriod]


class TargetAllocationUpdate(BaseModel):
    # asset_class -> target percentage (0-100), must sum to 100 if non-empty.
    targets: dict[str, DecimalStr]


class DriftRowRead(BaseModel):
    asset_class: str
    current_value_eur: DecimalStr
    current_pct: DecimalStr
    target_pct: DecimalStr
    drift_pp: DecimalStr
    drift_value_eur: DecimalStr


class RebalanceProposalRead(BaseModel):
    asset_class: str
    amount_eur: DecimalStr


class AllocationResponse(BaseModel):
    drift: list[DriftRowRead]
    rebalance_full: list[RebalanceProposalRead]
    # Only populated when ?contribution=<amount> was passed.
    rebalance_purchases_only: list[RebalanceProposalRead] | None = None


class DataQualityIssueRead(BaseModel):
    kind: str
    detail: str
    instrument_id: int | None = None
    instrument_name: str | None = None
    account_id: int | None = None
    age_days: int | None = None


class DataQualityResponse(BaseModel):
    issues: list[DataQualityIssueRead]


class SaverAllowanceUsage(BaseModel):
    year: int
    allowance_eur: DecimalStr
    realized_gains_eur: DecimalStr
    investment_income_eur: DecimalStr
    total_eur: DecimalStr
    remaining_eur: DecimalStr


class UnrealizedTaxEstimateRead(BaseModel):
    account_id: int
    instrument_id: int
    quantity: DecimalStr
    cost_basis_eur: DecimalStr
    current_value_eur: DecimalStr
    unrealized_pl_eur: DecimalStr
    estimated_tax_eur: DecimalStr


class TaxOverviewResponse(BaseModel):
    saver_allowance: SaverAllowanceUsage
    unrealized: list[UnrealizedTaxEstimateRead]
    vorabpauschale_reminder: str | None


class EtfCompositionSet(BaseModel):
    dimension: str
    # category -> weight percentage, e.g. {"North America": "60", "Europe": "40"}
    breakdown: dict[str, DecimalStr]


class EtfCompositionRow(BaseModel):
    dimension: str
    category: str
    weight_pct: DecimalStr


class LookThroughRowRead(BaseModel):
    category: str
    value_eur: DecimalStr


class LookThroughResponse(BaseModel):
    dimension: str
    rows: list[LookThroughRowRead]


class MilestoneResponse(BaseModel):
    scope: str
    current_value_eur: DecimalStr
    next_milestone_eur: DecimalStr
    monthly_savings_eur: DecimalStr
    assumed_annual_return_pct: DecimalStr
    months_to_reach: float | None
    estimated_date: date_ | None


class RebuildSnapshotsResponse(BaseModel):
    days_written: int


class ReconcileHoldingInput(BaseModel):
    isin: str
    quantity: DecimalStr


class ReconcileRequest(BaseModel):
    account: str
    as_of: date_
    holdings: list[ReconcileHoldingInput]


class ReconcileDifference(BaseModel):
    isin: str | None
    instrument_id: int | None
    instrument_name: str | None
    reported_quantity: DecimalStr | None
    computed_quantity: DecimalStr
    delta: DecimalStr
    matched: bool
    note: str | None = None


class ReconcileResponse(BaseModel):
    account_id: int
    as_of: date_
    differences: list[ReconcileDifference]


class ValuationAnchorCreate(BaseModel):
    instrument_id: int
    date: date_
    value_eur: DecimalStr
    method: str = "manual"
    confidence: str | None = None
    source: str | None = None
    note: str | None = None


class ValuationAnchorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    instrument_id: int
    date: date_
    value_eur: DecimalStr
    method: str
    confidence: str | None
    source: str | None
    note: str | None
    created_at: datetime


class HouseIndexPointCreate(BaseModel):
    series: str
    date: date_
    index_value: DecimalStr


class HouseIndexPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    series: str
    date: date_
    index_value: DecimalStr


class CpiIndexPointCreate(BaseModel):
    date: date_
    index_value: DecimalStr


class CpiIndexPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date_
    index_value: DecimalStr


class LoanCreate(BaseModel):
    account_id: int
    principal: DecimalStr
    rate_pct: DecimalStr
    start_date: date_
    fixed_until: date_ | None = None
    monthly_payment: DecimalStr
    payment_day: int = 1
    extra_repayment_allowance_pct: DecimalStr | None = None


class LoanUpdate(BaseModel):
    rate_pct: DecimalStr | None = None
    fixed_until: date_ | None = None
    monthly_payment: DecimalStr | None = None
    payment_day: int | None = None
    extra_repayment_allowance_pct: DecimalStr | None = None


class LoanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    principal: DecimalStr
    rate_pct: DecimalStr
    start_date: date_
    fixed_until: date_ | None
    monthly_payment: DecimalStr
    payment_day: int
    extra_repayment_allowance_pct: DecimalStr | None


class LoanStatus(BaseModel):
    loan: LoanRead
    balance_eur: DecimalStr
    ltv: DecimalStr | None = None
    house_value_eur: DecimalStr | None = None


class ErrorDetail(BaseModel):
    code: str
    params: dict = {}
