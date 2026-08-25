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
    TaxTreatment,
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
    tax_treatment: TaxTreatment | None = None
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
    tax_treatment: TaxTreatment | None = None
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
    tax_treatment: TaxTreatment | None
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
    # The benchmark's total return over the same window, on the same
    # basis as `return_pct`. Sent explicitly rather than left for the
    # client to derive from the curve's last point: the whole question
    # this view exists to answer is "did I beat it, by how much", and
    # that comparison should not depend on a client reimplementing the
    # convention correctly.
    benchmark_return_pct: float | None = None


class CalendarYearReturnRead(BaseModel):
    year: int
    # The part of the year actually covered. Clipped by inception at the
    # near end and by the last nightly snapshot at the far end.
    start_date: date_
    end_date: date_
    partial: bool
    # TWR over the year, measured from the previous 31 December's close so
    # the years chain back to the since-inception figure. None when the
    # window held no daily return at all — deliberately not 0.0, which
    # would read as "flat" rather than "nothing to report".
    return_pct: float | None
    # Same shadow-portfolio convention as PerformanceResponse's
    # benchmark_return_pct ("what if every contribution had gone into
    # this instead"), so the table and the chart can never disagree.
    benchmark_return_pct: float | None = None


class CalendarYearsResponse(BaseModel):
    scope: str
    # Always "twr". MWR is an annualised rate derived from the timing of
    # flows; slicing it per calendar year and reading the results as a
    # sequence would invite a comparison the number does not support.
    method: str
    years: list[CalendarYearReturnRead]


class InstrumentReturnRead(BaseModel):
    instrument_id: int
    name: str
    asset_class: str
    # This instrument's own window: the requested period clipped to when
    # it was actually first held, so a holding bought last month does not
    # claim a one-year return.
    start_date: date_
    end_date: date_
    return_pct: float | None
    # Current value, carried so the ranking is readable — a +400% return
    # on a 50 EUR position is noise, and a table of percentages alone
    # gives no way to tell.
    value_eur: DecimalStr


class InstrumentReturnsResponse(BaseModel):
    period: str
    method: str
    # The window the period resolved to, before each row clips it to its
    # own inception. Sent so a client can tell which rows are actually
    # shorter than what was asked for — comparing a row's start_date
    # against this is the only way to know, and repeating the same date on
    # every row instead says nothing.
    start_date: date_
    end_date: date_
    instruments: list[InstrumentReturnRead]


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
    """§20 Sparerpauschbetrag — a real allowance, only the excess is taxed."""

    model_config = ConfigDict(from_attributes=True)

    year: int
    allowance_eur: DecimalStr
    realized_gains_eur: DecimalStr
    investment_income_eur: DecimalStr
    vorabpauschale_eur: DecimalStr
    total_eur: DecimalStr
    remaining_eur: DecimalStr


class PrivateSaleAllowanceUsage(BaseModel):
    """§23 Freigrenze — a cliff, not an allowance. Reaching the limit
    makes the whole amount taxable, which is why `limit_exceeded` is a
    field of its own rather than something a client infers from
    `remaining_eur <= 0`."""

    model_config = ConfigDict(from_attributes=True)

    year: int
    exemption_limit_eur: DecimalStr
    realized_taxable_eur: DecimalStr
    realized_exempt_eur: DecimalStr
    remaining_eur: DecimalStr
    limit_exceeded: bool


class RegimeLiquidationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    gross_gain_eur: DecimalStr
    losses_eur: DecimalStr
    net_gain_eur: DecimalStr
    allowance_applied_eur: DecimalStr
    taxable_eur: DecimalStr
    tax_eur: DecimalStr
    tax_free_gain_eur: DecimalStr


class LiquidationSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    as_of: date_
    total_current_value_eur: DecimalStr
    total_cost_basis_eur: DecimalStr
    total_unrealized_pl_eur: DecimalStr
    capital_gains: RegimeLiquidationRead
    private_sale: RegimeLiquidationRead
    total_tax_eur: DecimalStr
    net_proceeds_eur: DecimalStr
    excluded_position_count: int


class UnrealizedTaxEstimateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: int
    instrument_id: int
    tax_treatment: TaxTreatment
    quantity: DecimalStr
    cost_basis_eur: DecimalStr
    current_value_eur: DecimalStr
    unrealized_pl_eur: DecimalStr
    tax_free_gain_eur: DecimalStr
    exposed_gain_eur: DecimalStr
    tax_free_quantity: DecimalStr
    next_tax_free_date: date_ | None
    estimated_tax_eur: DecimalStr


class VorabpauschaleEntryCreate(BaseModel):
    # The year the amount counts against the saver's allowance, i.e. the
    # year the broker debited it — not the year it accrued for.
    year: int = Field(ge=1, le=9999)
    amount_eur: DecimalStr = Field(ge=0)
    note: str | None = None


class VorabpauschaleEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    year: int
    amount_eur: DecimalStr
    note: str | None
    updated_at: datetime | None


class TaxOverviewResponse(BaseModel):
    saver_allowance: SaverAllowanceUsage
    private_sale_allowance: PrivateSaleAllowanceUsage
    liquidation: LiquidationSummaryRead
    unrealized: list[UnrealizedTaxEstimateRead]
    vorabpauschale: VorabpauschaleEntryRead | None
    vorabpauschale_reminder: str | None


class EtfCompositionSet(BaseModel):
    dimension: str
    # category -> weight percentage, e.g. {"North America": "60", "Europe": "40"}
    breakdown: dict[str, DecimalStr]


class EtfCompositionRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dimension: str
    category: str
    weight_pct: DecimalStr
    # None for breakdowns entered before this was tracked — unknown age,
    # not fresh. The data quality panel reports it either way.
    updated_at: datetime | None = None


class LookThroughRowRead(BaseModel):
    category: str
    value_eur: DecimalStr
    # The benchmark's weight for this category, None when no benchmark is
    # configured or it doesn't list the category. A row can carry a
    # benchmark weight with value_eur 0 — that is the interesting case of
    # holding nothing where the world holds something.
    benchmark_pct: DecimalStr | None = None


class LookThroughResponse(BaseModel):
    dimension: str
    rows: list[LookThroughRowRead]
    # Name of the yardstick the rows are compared against ("MSCI ACWI"),
    # None when none is configured for this dimension.
    benchmark_label: str | None = None


class BenchmarkSet(BaseModel):
    dimension: str
    label: str = Field(min_length=1)
    # category -> percentage of the world market, e.g. {"Europe": "14"}
    breakdown: dict[str, DecimalStr]


class BenchmarkRead(BaseModel):
    dimension: str
    label: str | None
    breakdown: dict[str, DecimalStr]


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


class EtfSplitRowRead(BaseModel):
    instrument_id: int
    name: str
    value_eur: DecimalStr
    emerging_eur: DecimalStr
    emerging_pct: DecimalStr


class EtfSplitResponse(BaseModel):
    """GET /api/look-through/etf-split — developed vs. emerging across the
    fund holdings, with each fund's own contribution."""

    developed_eur: DecimalStr
    emerging_eur: DecimalStr
    total_eur: DecimalStr
    # None when no funds are held: a share of nothing is not zero.
    emerging_pct: DecimalStr | None
    target_emerging_pct: DecimalStr | None
    drift_pp: DecimalStr | None
    rows: list[EtfSplitRowRead]


class EtfSplitTargetSet(BaseModel):
    # None clears the target.
    emerging_pct: DecimalStr | None = None


class ContributionsResponse(BaseModel):
    """GET /api/contributions — what went in over a window (spec 4.3)."""

    start_date: date_
    end_date: date_
    # Asset class -> net invested (purchases minus sales). Classes with a
    # net of exactly zero are omitted rather than reported as 0.
    by_asset_class: dict[str, DecimalStr]
    total_invested: DecimalStr
    # Positive means principal went down over the window.
    debt_repaid: DecimalStr
    net_worth_change: DecimalStr


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
