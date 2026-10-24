from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel
from app.schemas.money import MoneyOut

GoalStatusLiteral = Literal["active", "completed", "archived"]
GoalEntryType = Literal["contribution", "withdrawal"]


class GoalCreate(ApiModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=1000)
    target_amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    target_date: date | None = None


class GoalUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=1000)
    target_amount_minor: int | None = Field(default=None, gt=0)
    target_date: date | None = None
    is_archived: bool | None = None


class GoalOut(ApiModel):
    id: int
    name: str
    description: str | None
    target: MoneyOut
    saved: MoneyOut
    remaining: MoneyOut
    progress_percent: float
    currency: str
    target_date: date | None
    status: GoalStatusLiteral
    created_at: datetime


class GoalEntryCreate(ApiModel):
    type: GoalEntryType
    amount_minor: int = Field(gt=0)
    occurred_at: datetime
    comment: str | None = Field(default=None, max_length=500)


class GoalEntryOut(ApiModel):
    id: int
    goal_id: int
    type: GoalEntryType
    amount: MoneyOut
    occurred_at: datetime
    comment: str | None
