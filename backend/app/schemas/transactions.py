from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel
from app.schemas.money import MoneyOut

TransactionType = Literal["income", "expense"]


class TransactionCreate(ApiModel):
    account_id: int
    category_id: int
    type: TransactionType
    amount_minor: int = Field(gt=0)
    occurred_at: datetime
    comment: str | None = Field(default=None, max_length=500)


class TransactionUpdate(ApiModel):
    account_id: int | None = None
    category_id: int | None = None
    type: TransactionType | None = None
    amount_minor: int | None = Field(default=None, gt=0)
    occurred_at: datetime | None = None
    comment: str | None = Field(default=None, max_length=500)


class TransactionOut(ApiModel):
    id: int
    account_id: int
    category_id: int
    type: str
    amount: MoneyOut
    occurred_at: datetime
    comment: str | None
    # Заполнены, если операция — движение денег от погашения долга.
    debt_id: int | None = None
    debt_name: str | None = None
