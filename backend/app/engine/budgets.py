"""Чистая логика бюджетов: остаток, процент использования, статус.

Как и весь app/engine/, модуль не зависит ни от FastAPI, ни от SQLAlchemy.
spent никогда не хранится — его всегда считает вызывающий код (см.
app/api/v1/budgets.py) суммированием существующих Transaction за месяц,
поэтому бюджет не может разойтись с фактическими расходами.
"""

from __future__ import annotations

import enum
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from app.engine.money import Money

__all__ = [
    "BudgetStatus",
    "WARNING_THRESHOLD_PERCENT",
    "calculate_remaining",
    "calculate_usage_percent",
    "calculate_budget_status",
    "calculate_budget_usage",
    "month_bounds",
]

WARNING_THRESHOLD_PERCENT = Decimal(80)


class BudgetStatus(str, enum.Enum):
    ok = "ok"
    warning = "warning"
    exceeded = "exceeded"


def calculate_remaining(budget_amount: Money, spent: Money) -> Money:
    """Остаток может быть отрицательным — это и есть признак превышения."""
    return budget_amount - spent


def calculate_usage_percent(spent: Money, budget_amount: Money) -> Decimal:
    """Процент использования, округлённый до 0.1.

    Бюджет = 0 — вырожденный случай (делить не на что): возвращаем 0, а не
    бросаем ZeroDivisionError. Статус для этого случая считается отдельно
    в calculate_budget_status и не полагается на этот процент — иначе
    "потратили что-то при бюджете 0" молча показало бы 0% вместо "превышен".
    """
    if budget_amount.minor == 0:
        return Decimal(0)
    ratio = spent.ratio_to(budget_amount)
    return (ratio * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def calculate_budget_status(spent: Money, budget_amount: Money) -> BudgetStatus:
    if budget_amount.minor == 0:
        return BudgetStatus.exceeded if spent.minor > 0 else BudgetStatus.ok
    usage_percent = calculate_usage_percent(spent, budget_amount)
    if usage_percent > 100:
        return BudgetStatus.exceeded
    if usage_percent >= WARNING_THRESHOLD_PERCENT:
        return BudgetStatus.warning
    return BudgetStatus.ok


def calculate_budget_usage(
    spent: Money, budget_amount: Money
) -> tuple[Money, Decimal, BudgetStatus]:
    """Остаток, процент и статус одним вызовом — то, что нужно API-ответу."""
    remaining = calculate_remaining(budget_amount, spent)
    usage_percent = calculate_usage_percent(spent, budget_amount)
    status = calculate_budget_status(spent, budget_amount)
    return remaining, usage_percent, status


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """Начало и конец календарного месяца включительно, в UTC."""
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        next_month_start = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month_start = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    end = next_month_start - timedelta(microseconds=1)
    return start, end
