from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel
from app.schemas.money import MoneyOut

BudgetStatusLiteral = Literal["ok", "warning", "exceeded"]


class BudgetCreate(ApiModel):
    category_id: int
    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)


class BudgetUpdate(ApiModel):
    # Категория/период/валюта — часть идентичности бюджета (см. уникальный
    # индекс в модели); чтобы не путаться с конфликтами уникальности при
    # частичном PATCH, меняется только сумма. Нужен другой период — новый
    # бюджет, старый удаляется.
    amount_minor: int | None = Field(default=None, gt=0)


class BudgetOut(ApiModel):
    id: int
    category_id: int
    category_name: str
    category_icon: str | None
    amount: MoneyOut
    year: int
    month: int
    spent: MoneyOut
    remaining: MoneyOut
    usage_percent: float
    status: BudgetStatusLiteral
