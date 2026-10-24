from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel
from app.schemas.money import MoneyOut

RecurringType = Literal["income", "expense"]
Frequency = Literal["daily", "weekly", "monthly", "yearly"]


class RecurringTransactionCreate(ApiModel):
    type: RecurringType
    account_id: int
    category_id: int
    amount_minor: int = Field(gt=0)
    comment: str | None = Field(default=None, max_length=500)
    start_date: date
    end_date: date | None = None
    frequency: Frequency
    # Необязательно: по умолчанию правило начинает генерировать со
    # start_date. Явное значение нужно, если этот месяц уже занесён вручную
    # и генерацию нужно начать позже.
    next_run_date: date | None = None


class RecurringTransactionUpdate(ApiModel):
    account_id: int | None = None
    category_id: int | None = None
    amount_minor: int | None = Field(default=None, gt=0)
    comment: str | None = Field(default=None, max_length=500)
    end_date: date | None = None
    is_active: bool | None = None


class RecurringTransactionOut(ApiModel):
    id: int
    type: RecurringType
    account_id: int
    account_name: str
    category_id: int
    category_name: str
    category_icon: str | None
    amount: MoneyOut
    comment: str | None
    start_date: date
    end_date: date | None
    frequency: Frequency
    next_run_date: date
    is_active: bool


class RecurringProcessResultOut(ApiModel):
    created_transactions: int
    deactivated_rules: int
