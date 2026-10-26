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


# --- сравнение периодов (Stage 3D) ---------------------------------------------------


class ComparisonWindowOut(ApiModel):
    date_from: dt.date
    date_to: dt.date
    label: str
    days: int


class ChangeOut(ApiModel):
    """current − previous. percent — None, если база нулевая (zero_base) или
    прошлый период не покрыт данными (insufficient_history)."""

    current: MoneyOut
    previous: MoneyOut
    delta: MoneyOut
    percent: float | None
    percent_null_reason: Literal["zero_base", "insufficient_history"] | None


class CategoryChangeOut(ChangeOut):
    category_id: int
    label: str


class LargeExpensesComparisonOut(ApiModel):
    """Крупные расходы обоих периодов по ОДНОМУ порогу — иначе сравнение
    количества не имеет смысла."""

    threshold: MoneyOut
    current_count: int
    previous_count: int
    total: ChangeOut


class ShareComparisonOut(ApiModel):
    """Доля «Прочих расходов» в расходах периода, в процентах, и изменение
    в процентных пунктах."""

    current: float | None
    previous: float | None
    delta_points: float | None


class TransfersExcludedOut(ApiModel):
    current_count: int
    current_total: MoneyOut
    previous_count: int
    previous_total: MoneyOut


class PossibleInternalPairsOut(ApiModel):
    """Расход и доход одной суммы в один день на разных своих счетах. Только
    подозрение: суммы НЕ исключены из доходов и расходов."""

    count: int
    total: MoneyOut


class CurrencyComparisonOut(ApiModel):
    currency: str
    confidence: Confidence
    income: ChangeOut
    expense: ChangeOut
    net: ChangeOut
    debt_repayments: ChangeOut
    expense_without_debt_repayments: ChangeOut
    categories_up: list[CategoryChangeOut]
    categories_down: list[CategoryChangeOut]
    categories: list[CategoryChangeOut]
    categories_truncated: bool
    large_expenses: LargeExpensesComparisonOut | None
    large_expenses_null_reason: str | None
    other_share: ShareComparisonOut
    transfers_excluded: TransfersExcludedOut
    possible_internal_pairs: PossibleInternalPairsOut
    summary: str
    warnings: list[str]


class PeriodComparisonOut(ApiModel):
    key: InsightPeriodKey
    current: ComparisonWindowOut
    previous: ComparisonWindowOut
    same_days: bool
    note: str
    by_currency: list[CurrencyComparisonOut]
    unavailable_reason: str | None


class InsightsOut(ApiModel):
    generated_at: dt.datetime
    today: dt.date
    period: InsightPeriodOut
    currencies: list[str]
    insights: list[InsightOut]
    unavailable: list[UnavailableInsightOut]
    comparison: PeriodComparisonOut | None = None


class InsightExplainRequest(ApiModel):
    insight_id: str = Field(min_length=1, max_length=100)
    period: InsightPeriodKey = "current_month"


# --- финансовые предупреждения (Stage 3E) ---------------------------------------------

WarningType = Literal["budget_exceeded", "budget_pace_risk", "large_expense", "category_spike", "goal_overdue"]


class WarningPeriodOut(ApiModel):
    date_from: dt.date
    date_to: dt.date
    label: str


class FinancialWarningOut(ApiModel):
    """Актуальное предупреждение, посчитанное backend по текущим данным.

    key — стабильный ключ события (тип, сущность, период): одно событие
    даёт один ключ при любом числе запросов, поэтому по нему можно
    скрывать предупреждение и не показывать его повторно. kind различает
    факт (бюджет уже превышен, срок цели прошёл), оценку (риск по темпу
    трат) и наблюдение (крупный расход, рост категории)."""

    key: str
    type: WarningType
    kind: Literal["fact", "estimate", "observation"]
    severity: Literal["warning", "attention"]
    title: str
    message: str
    currency: str | None
    metrics: list[InsightMetricOut]
    period: WarningPeriodOut
    recommendation: str | None
    link: InsightLinkOut | None


class LargeExpenseGroupOut(ApiModel):
    """Сводка предупреждений о крупных расходах одной валюты: сколько
    операций и на какую сумму (сумма посчитана backend, только в одной
    валюте). keys — ключи предупреждений группы; сами предупреждения
    остаются в warnings и скрываются по своим ключам."""

    currency: str
    count: int
    total: MoneyOut
    keys: list[str]
    period: WarningPeriodOut


class WarningsOut(ApiModel):
    generated_at: dt.datetime
    today: dt.date
    warnings: list[FinancialWarningOut]
    large_expense_groups: list[LargeExpenseGroupOut] = []
    # Почему часть проверок не выполнена или ограничена (мало данных, много
    # «Прочего» и т. п.) — чтобы отсутствие предупреждения не выглядело как
    # «всё хорошо», когда проверить было нельзя.
    limitations: list[str]
