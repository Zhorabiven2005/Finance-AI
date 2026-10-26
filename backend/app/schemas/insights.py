"""Финансовые инсайты (Stage 3C): GET /api/v1/insights.

Каждый инсайт — готовый вывод, посчитанный backend: заголовок, тип,
показатели, период и валюта, понятный текст, уверенность и ограничения.
Числа приходят в minor-единицах с кодом валюты (MoneyOut); суммы разных
валют не складываются — у инсайта одна валюта или у каждой строки своя.
Названия счетов и категорий — пользовательские строки: они очищены
(sanitize_label) и для модели считаются данными, а не инструкциями.
Комментарии к операциям в инсайты не попадают вовсе.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel
from app.schemas.money import MoneyOut

InsightType = Literal[
    "cash_flow",
    "spending_structure",
    "large_expenses",
    "recurring_expenses",
    "budgets",
    "goals",
    "data_quality",
]
InsightPeriodKey = Literal["current_month", "previous_month", "last_3_months"]
Severity = Literal["info", "attention", "warning"]
Confidence = Literal["high", "medium", "low"]


class InsightPeriodOut(ApiModel):
    key: InsightPeriodKey | Literal["today"]
    date_from: dt.date
    date_to: dt.date
    label: str
    complete: bool


class InsightMetricOut(ApiModel):
    """Один показатель: ровно одно из money / percent / count заполнено."""

    label: str
    money: MoneyOut | None = None
    percent: float | None = None
    count: int | None = None


class InsightItemOut(ApiModel):
    label: str
    money: MoneyOut | None = None
    percent: float | None = None
    date: dt.date | None = None
    note: str | None = None


class InsightLinkOut(ApiModel):
    to: str
    label: str


class InsightOut(ApiModel):
    id: str
    type: InsightType
    title: str
    severity: Severity
    confidence: Confidence
    period: InsightPeriodOut
    currency: str | None
    metrics: list[InsightMetricOut]
    items: list[InsightItemOut]
    summary: str
    limitations: list[str]
    link: InsightLinkOut | None


class UnavailableInsightOut(ApiModel):
    """Почему вывода нет: мало данных, нечего показывать или неприменимо."""

    type: InsightType
    currency: str | None = None
    kind: Literal["insufficient_data", "nothing_found", "not_applicable"]
    reason: str


class InsightsOut(ApiModel):
    generated_at: dt.datetime
    today: dt.date
    period: InsightPeriodOut
    currencies: list[str]
    insights: list[InsightOut]
    unavailable: list[UnavailableInsightOut]


class InsightExplainRequest(ApiModel):
    insight_id: str = Field(min_length=1, max_length=100)
    period: InsightPeriodKey = "current_month"
