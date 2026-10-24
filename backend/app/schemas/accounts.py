from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel
from app.schemas.money import MoneyOut

AccountType = Literal["bank", "cash", "other"]


class AccountCreate(ApiModel):
    name: str = Field(min_length=1, max_length=100)
    type: AccountType
    currency: str = Field(min_length=3, max_length=3)
    initial_balance_minor: int = 0
    is_active: bool = True


class AccountUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    type: AccountType | None = None
    is_active: bool | None = None


class AccountOut(ApiModel):
    id: int
    name: str
    type: str
    currency: str
    initial_balance_minor: int
    is_active: bool
    balance: MoneyOut
