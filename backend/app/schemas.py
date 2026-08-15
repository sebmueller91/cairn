from decimal import Decimal
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.models import AccountType, AssetClass, LiquidityTier, ValuationMode

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
    opened_at: date | None = None
    verified_from: date | None = None
    sort_order: int = 0


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    institution: str | None = None
    opened_at: date | None = None
    closed_at: date | None = None
    verified_from: date | None = None
    sort_order: int | None = None
    archived: bool | None = None


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: AccountType
    currency: str
    institution: str | None
    opened_at: date | None
    closed_at: date | None
    verified_from: date | None
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


class ErrorDetail(BaseModel):
    code: str
    params: dict = {}
