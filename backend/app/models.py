import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base
from app.db_types import Money, Quantity


class AccountType(str, enum.Enum):
    BROKERAGE = "BROKERAGE"
    CRYPTO_WALLET = "CRYPTO_WALLET"
    PHYSICAL_STORAGE = "PHYSICAL_STORAGE"
    REAL_ESTATE = "REAL_ESTATE"
    VEHICLE = "VEHICLE"
    LOAN = "LOAN"
    CASH = "CASH"


class AssetClass(str, enum.Enum):
    EQUITY = "EQUITY"
    BOND = "BOND"
    COMMODITY = "COMMODITY"
    CRYPTO = "CRYPTO"
    REAL_ESTATE = "REAL_ESTATE"
    VEHICLE = "VEHICLE"
    CASH = "CASH"
    LIABILITY = "LIABILITY"


class ValuationMode(str, enum.Enum):
    MARKET = "MARKET"
    ANCHORED = "ANCHORED"
    MODELED = "MODELED"
    AMORTIZING_LIABILITY = "AMORTIZING_LIABILITY"
    NOMINAL = "NOMINAL"


class LiquidityTier(str, enum.Enum):
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


class TransactionType(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    INTEREST = "INTEREST"
    FEE = "FEE"
    TAX = "TAX"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSFER = "TRANSFER"
    SPLIT = "SPLIT"
    VALUATION = "VALUATION"
    OPENING_BALANCE = "OPENING_BALANCE"
    BALANCE_STATEMENT = "BALANCE_STATEMENT"
    LOAN_PAYMENT = "LOAN_PAYMENT"
    EXTRA_REPAYMENT = "EXTRA_REPAYMENT"


class DatePrecision(str, enum.Enum):
    DAY = "day"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class PriceMode(str, enum.Enum):
    EXACT = "exact"
    AUTO = "auto"


class TxnSource(str, enum.Enum):
    MANUAL = "manual"
    AGENT = "agent"
    IMPORT = "import"


class Account(Base):
    __tablename__ = "account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[AccountType] = mapped_column(Enum(AccountType), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    institution: Mapped[str | None] = mapped_column(String, nullable=True)
    opened_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    closed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    verified_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    actor: Mapped[TxnSource] = mapped_column(Enum(TxnSource), nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)  # create|update|delete
    entity: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[str] = mapped_column(String, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String, nullable=False)
    diff_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class Instrument(Base):
    __tablename__ = "instrument"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True, unique=True)
    wkn: Mapped[str | None] = mapped_column(String(6), nullable=True)
    ticker: Mapped[str | None] = mapped_column(String, nullable=True)
    asset_class: Mapped[AssetClass] = mapped_column(Enum(AssetClass), nullable=False)
    valuation_mode: Mapped[ValuationMode] = mapped_column(
        Enum(ValuationMode), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    region: Mapped[str | None] = mapped_column(String, nullable=True)
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
    liquidity_tier: Mapped[LiquidityTier | None] = mapped_column(
        Enum(LiquidityTier), nullable=True
    )
    ter_pct: Mapped[Quantity | None] = mapped_column(Quantity, nullable=True)
    # Physical units only (metals): grams of fine metal per one unit of
    # `quantity` — e.g. 31.1035 for a one-troy-ounce coin (spec 3.2).
    fine_weight_g: Mapped[Quantity | None] = mapped_column(Quantity, nullable=True)
    # MODELED/ANCHORED parameters (car depreciation inputs, house index
    # series choice) — see docs/data-model.md, resolved ambiguity (b): a
    # JSON blob rather than a dedicated table, since these are set once at
    # creation and the parameter set varies per valuation_mode.
    valuation_config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class PricePoint(Base):
    """Fetched externally (phase 2). Table exists from phase 1 so
    price_mode='auto' has somewhere to look, even before anything
    populates it."""

    __tablename__ = "price_point"

    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instrument.id"), primary_key=True
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[Quantity] = mapped_column(Quantity, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    quality: Mapped[str] = mapped_column(String, nullable=False, default="ok")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PriceSource(Base):
    """Ordered fallback chain per instrument (ADR 0010). Swapping a broken
    provider is a row change here, never a deploy."""

    __tablename__ = "price_source"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instrument.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)
    provider_symbol: Mapped[str] = mapped_column(String, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_fetch_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class DailySnapshot(Base):
    """Cache only — always fully reconstructible from txn/price_point/
    fx_rate via a rebuild (ADR 0003). Never a second source of truth."""

    __tablename__ = "daily_snapshot"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    scope_type: Mapped[str] = mapped_column(String, primary_key=True)
    scope_id: Mapped[str] = mapped_column(String, primary_key=True)
    quantity: Mapped[Quantity | None] = mapped_column(Quantity, nullable=True)
    value_eur: Mapped[Money] = mapped_column(Money, nullable=False)
    cost_basis_eur: Mapped[Money | None] = mapped_column(Money, nullable=True)


class SnapshotWatermark(Base):
    """Per-account dirty-from date driving incremental rebuilds (ADR 0003).
    A bug here only ever degrades to "slower," never "wrong" — the full
    rebuild endpoint ignores this table entirely."""

    __tablename__ = "snapshot_watermark"

    account_id: Mapped[int] = mapped_column(
        ForeignKey("account.id"), primary_key=True
    )
    dirty_from_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class FxRate(Base):
    """1 unit of `currency` = `eur_rate` EUR. Simplified from the spec's
    base/quote pair sketch since the app only ever converts to EUR
    (docs/data-model.md)."""

    __tablename__ = "fx_rate"

    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    eur_rate: Mapped[Quantity] = mapped_column(Quantity, nullable=False)


class ImportBatch(Base):
    """Every txn belongs to exactly one batch, including a single manual
    entry (a batch of one) — this is what makes batch rollback a uniform
    primitive rather than a special case for bulk imports only
    (docs/data-model.md, invariant 4)."""

    __tablename__ = "import_batch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[TxnSource] = mapped_column(Enum(TxnSource), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Txn(Base):
    __tablename__ = "txn"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    import_batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batch.id"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    date_precision: Mapped[DatePrecision] = mapped_column(
        Enum(DatePrecision), nullable=False, default=DatePrecision.DAY
    )
    type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType), nullable=False
    )
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), nullable=False)
    instrument_id: Mapped[int | None] = mapped_column(
        ForeignKey("instrument.id"), nullable=True
    )
    quantity: Mapped[Quantity | None] = mapped_column(Quantity, nullable=True)
    # Native-currency price/amount, as printed on the statement — never
    # pre-converted by the caller (spec 7.2 pitfalls). NULL when
    # price_mode=auto and no exact figure was supplied.
    price: Mapped[Quantity | None] = mapped_column(Quantity, nullable=True)
    price_mode: Mapped[PriceMode] = mapped_column(
        Enum(PriceMode), nullable=False, default=PriceMode.EXACT
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    fx_rate: Mapped[Quantity | None] = mapped_column(Quantity, nullable=True)
    split_ratio: Mapped[Quantity | None] = mapped_column(Quantity, nullable=True)
    fees: Mapped[Money] = mapped_column(Money, nullable=False, default=0)
    tax: Mapped[Money] = mapped_column(Money, nullable=False, default=0)
    amount_eur: Mapped[Money] = mapped_column(Money, nullable=False)
    # TRANSFER destination account — one row models both legs (spec, still-
    # open decision (d) in docs/data-model.md: proceeding on this basis).
    counter_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("account.id"), nullable=True
    )
    provisional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batch.id"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[TxnSource] = mapped_column(Enum(TxnSource), nullable=False)
    # Hash of the original write payload — the only reliable way to tell an
    # identical resend (idempotent no-op) from a genuinely different
    # payload reusing the same external_id (409), since not every input
    # field (e.g. the raw `amount` for non-BUY/SELL types) survives into
    # stored columns once amount_eur is derived.
    payload_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ValuationAnchor(Base):
    """A point the ANCHORED/MODELED valuation curve is pinned to (spec
    3.4/3.3): the house's purchase price, a later appraisal, a car
    trade-in offer. Distinct from `txn` — an anchor never moves cash or
    quantity, it just recalibrates a formula."""

    __tablename__ = "valuation_anchor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instrument.id"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    value_eur: Mapped[Money] = mapped_column(Money, nullable=False)
    method: Mapped[str] = mapped_column(String, nullable=False)  # purchase|appraisal|trade_in|other
    confidence: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Loan(Base):
    __tablename__ = "loan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), nullable=False)
    principal: Mapped[Money] = mapped_column(Money, nullable=False)
    rate_pct: Mapped[Quantity] = mapped_column(Quantity, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    fixed_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    monthly_payment: Mapped[Money] = mapped_column(Money, nullable=False)
    payment_day: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    extra_repayment_allowance_pct: Mapped[Quantity | None] = mapped_column(
        Quantity, nullable=True
    )


class HousePriceIndexPoint(Base):
    """Destatis GENESIS table 61262 (spec 3.4), one series per district
    type. Populated by the fetch job — real Destatis credentials require
    a one-off registration the app can't do on its own, so this table can
    also be filled by hand until that's done."""

    __tablename__ = "house_price_index_point"

    series: Mapped[str] = mapped_column(String, primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    index_value: Mapped[Quantity] = mapped_column(Quantity, nullable=False)


class CpiIndexPoint(Base):
    """German CPI (spec 4.6, "annual maintenance is enough") for the
    wealth curve's real-vs-nominal view. Same manual-entry story as
    HousePriceIndexPoint: Destatis GENESIS needs a one-off registration
    this app can't complete on its own, so this table is filled by hand
    until that exists — a real fetch job would read from the same table
    without touching anything downstream."""

    __tablename__ = "cpi_index_point"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    index_value: Mapped[Quantity] = mapped_column(Quantity, nullable=False)


class EtfComposition(Base):
    """ETF look-through (spec 4.4): "a region/sector breakdown maintained
    per ETF (entered by hand from the factsheet; it rarely changes)."
    dimension is typically 'region' or 'sector'; category is a factsheet
    label ('North America', 'Technology', ...). weight_pct rows for one
    (instrument_id, dimension) pair are expected to sum to ~100 but this
    isn't enforced at the schema level — a factsheet's own rounding
    already doesn't always hit exactly 100."""

    __tablename__ = "etf_composition"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"), primary_key=True)
    dimension: Mapped[str] = mapped_column(String, primary_key=True)
    category: Mapped[str] = mapped_column(String, primary_key=True)
    weight_pct: Mapped[Quantity] = mapped_column(Quantity, nullable=False)
