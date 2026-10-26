from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel
from app.schemas.money import MoneyOut

TransactionType = Literal["income", "expense"]
# Назначение операции (Stage 3F); None — обычный доход или расход.
TransactionPurpose = Literal["own_transfer", "external_transfer", "debt_repayment"]


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
    # Назначение, выбранное пользователем (Stage 3F), и связанные объекты.
    purpose: TransactionPurpose | None = None
    purpose_account_id: int | None = None
    purpose_debt_id: int | None = None


class TransactionPurposeUpdate(ApiModel):
    """Ручная классификация операции. purpose=None возвращает обычный тип.

    own_transfer — нужен purpose_account_id (второй свой счёт той же валюты);
    external_transfer — дополнительных полей нет; debt_repayment — только у
    расхода, purpose_debt_id необязателен (долг «я должен» той же валюты)."""

    purpose: TransactionPurpose | None
    purpose_account_id: int | None = Field(default=None, gt=0)
    purpose_debt_id: int | None = Field(default=None, gt=0)
