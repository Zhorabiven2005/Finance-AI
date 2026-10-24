from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from app.schemas.common import ApiModel
from app.schemas.money import MoneyOut


class AnalyticsSummaryOut(ApiModel):
    income: MoneyOut
    expense: MoneyOut
    balance: MoneyOut
    transaction_count: int


class PeriodComparisonOut(ApiModel):
    has_previous_data: bool
    previous_income: MoneyOut
    previous_expense: MoneyOut
    # None значит "процент посчитать нельзя" (в прошлом периоде было 0) —
    # это НЕ то же самое, что 0%, и frontend не должен рисовать стрелку.
    income_change_percent: float | None
    expense_change_percent: float | None


class TimeseriesPointOut(ApiModel):
    period_start: date
    income: MoneyOut
    expense: MoneyOut


class CategoryBreakdownItemOut(ApiModel):
    category_id: int
    category_name: str
    category_icon: str | None = None
    amount: MoneyOut
    percent: float


class TopExpenseItemOut(ApiModel):
    transaction_id: int
    amount: MoneyOut
    category_name: str
    category_icon: str | None = None
    account_name: str
    occurred_at: datetime
    comment: str | None


class AnalyticsOut(ApiModel):
    date_from: datetime
    date_to: datetime
    currency: str
    granularity: Literal["day", "week", "month"]
    summary: AnalyticsSummaryOut
    comparison: PeriodComparisonOut
    timeseries: list[TimeseriesPointOut]
    category_breakdown: list[CategoryBreakdownItemOut]
    top_expenses: list[TopExpenseItemOut]
