"""DTO локального AI-помощника (Stage 3A): статус Ollama и сводка для промпта.

Сводка (AssistantDigest) — компактная проекция read-only финансового
контекста Stage 2F (app/schemas/context.py). Новых финансовых расчётов в ней
нет: все суммы и показатели уже посчитаны приложением. Каждая сумма несёт
minor-единицы, валюту и готовую строку display, чтобы модели не приходилось
ничего пересчитывать. Свободного текста (комментариев, описаний) нет;
пользовательские названия лежат только в полях label и остаются
недоверенными данными.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from app.assistant.ollama import AssistantState
from app.schemas.context import ContextModel, DataQualityCode

# --- статус -------------------------------------------------------------------


class AssistantModelOut(ContextModel):
    name: str
    available: bool
    local: bool | None
    size_bytes: int | None
    parameter_size: str | None
    quantization: str | None


class AssistantServerOut(ContextModel):
    url: str
    available: bool
    version: str | None


class AssistantStatusOut(ContextModel):
    enabled: bool
    provider: Literal["ollama"]
    state: AssistantState
    ready: bool
    message: str
    server: AssistantServerOut
    model: AssistantModelOut
    checked_at: datetime


# --- сводка ---------------------------------------------------------------------


class DigestMoney(ContextModel):
    minor: int
    currency: str
    display: str


class DigestMeta(ContextModel):
    context_schema_version: str
    generated_at: datetime
    today: date
    today_utc: date
    local_and_utc_dates_differ: bool
    base_currency: str
    currencies: list[str]
    window_start: date
    window_end: date
    horizon_end: date


class DigestQualityNote(ContextModel):
    code: DataQualityCode
    text: str
    count: int | None = None


class DigestIndicators(ContextModel):
    currency: str
    income_last_month: DigestMoney
    expense_last_month: DigestMoney
    net_last_month: DigestMoney
    expense_change_percent: float | None
    expense_change_null_reason: str | None
    avg_monthly_income: DigestMoney | None
    avg_monthly_expense: DigestMoney | None
    window_months: int
    months_with_income: int
    months_with_expense: int
    savings_rate_percent: float | None
    savings_rate_null_reason: str | None
    active_accounts_net_position: DigestMoney
    debt_to_avg_monthly_income: float | None
    debt_ratio_null_reason: str | None
    overdue_debts: int
    debt_deadlines_in_horizon: int


class DigestAccount(ContextModel):
    label: str
    currency: str
    balance: DigestMoney


class DigestBudget(ContextModel):
    label: str
    currency: str
    limit: DigestMoney
    spent: DigestMoney
    remaining: DigestMoney
    usage_percent: float
    status: Literal["ok", "warning", "exceeded"]


class DigestDebt(ContextModel):
    label: str
    direction: Literal["i_owe", "owed_to_me"]
    currency: str
    remaining: DigestMoney
    paid_percent: float
    due_date: date | None
    due_state: str
    days_until_due: int | None


class DigestGoal(ContextModel):
    label: str
    status: Literal["active", "completed", "archived"]
    currency: str
    target: DigestMoney
    saved: DigestMoney
    remaining: DigestMoney
    progress_percent: float
    target_date: date | None
    months_left: int | None
    required_monthly: DigestMoney | None
    plan_null_reason: str | None


class DigestForecastItem(ContextModel):
    label: str
    flow: Literal["in", "out"]
    occurs_on: date
    date_status: Literal["upcoming", "due_today", "timezone_ambiguous", "past_unprocessed"]
    amount: DigestMoney


class DigestForecastTotal(ContextModel):
    currency: str
    outflow: DigestMoney
    inflow: DigestMoney
    occurrences: int


class DigestMonthFlow(ContextModel):
    year: int
    month: int
    complete: bool
    currency: str
    income: DigestMoney
    expense: DigestMoney
    net: DigestMoney


class DigestCategory(ContextModel):
    currency: str
    label: str
    amount: DigestMoney
    share_percent: float


class AssistantDigest(ContextModel):
    meta: DigestMeta
    data_quality: list[DigestQualityNote]
    indicators: list[DigestIndicators]
    accounts: list[DigestAccount]
    budgets: list[DigestBudget]
    debts: list[DigestDebt]
    goals: list[DigestGoal]
    recurring_forecast: list[DigestForecastItem]
    recurring_forecast_totals: list[DigestForecastTotal]
    cash_flow: list[DigestMonthFlow]
    top_categories: list[DigestCategory]
    unread_notifications: int
    # Списки, обрезанные лимитами сводки (полные данные — в /api/v1/context).
    truncated_lists: list[str]


class ChatMessageIn(ContextModel):
    """Реплика диалога из браузера. Роли system нет — правила задаёт только
    backend. Длина проверяется в API по настройкам ASSISTANT_*."""

    role: Literal["user", "assistant"]
    content: str


class ChatRequest(ContextModel):
    messages: list[ChatMessageIn]


class AssistantContextPreviewOut(ContextModel):
    """Ровно то, что в Stage 3B получит модель: структура и её текст."""

    digest: AssistantDigest
    text: str
    estimated_tokens: int
    token_budget: int
    omitted_sections: list[str]
