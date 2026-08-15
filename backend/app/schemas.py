from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import AccountType


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


class ErrorDetail(BaseModel):
    code: str
    params: dict = {}
