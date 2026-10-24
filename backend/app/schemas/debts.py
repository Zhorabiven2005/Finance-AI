from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel
from app.schemas.money import MoneyOut

DebtDirection = Literal["i_owe", "owed_to_me"]
DebtStatus = Literal["active", "partially_paid", "paid"]
DebtDueState = Literal["none", "upcoming", "soon", "today", "overdue", "paid"]


class DebtCreate(ApiModel):
    counterparty_name: str = Field(min_length=1, max_length=200)
    direction: DebtDirection
    principal_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    due_date: date | None = None
    comment: str | None = Field(default=None, max_length=500)


class DebtUpdate(ApiModel):
    counterparty_name: str | None = Field(default=None, min_length=1, max_length=200)
    due_date: date | None = None
    comment: str | None = Field(default=None, max_length=500)


class DebtOut(ApiModel):
    id: int
    counterparty_name: str
    direction: DebtDirection
    principal: MoneyOut
    paid: MoneyOut
    remaining: MoneyOut
    status: DebtStatus
    due_date: date | None
    comment: str | None
    # Вычисляемые поля Stage 2E: в БД не хранятся.
    paid_percent: float = 0.0
    due_state: DebtDueState = "none"
    days_until_due: int | None = None
    created_at: datetime | None = None


class DebtPaymentCreate(ApiModel):
    amount_minor: int = Field(gt=0)
    paid_at: datetime
    account_id: int | None = None
    comment: str | None = Field(default=None, max_length=500)


class DebtPaymentUpdate(ApiModel):
    """Частичное изменение платежа. account_id=null явно отвязывает счёт
    (различается с "поле не передано" через model_fields_set)."""

    amount_minor: int | None = Field(default=None, gt=0)
    paid_at: datetime | None = None
    account_id: int | None = None
    comment: str | None = Field(default=None, max_length=500)


class DebtPaymentOut(ApiModel):
    id: int
    debt_id: int
    account_id: int | None
    transaction_id: int | None
    amount: MoneyOut
    paid_at: datetime
    comment: str | None
