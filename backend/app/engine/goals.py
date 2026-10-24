"""Чистая логика финансовых целей: остаток, процент выполнения, статус.

Как и весь app/engine/, модуль не зависит ни от FastAPI, ни от SQLAlchemy.
saved (накопленная сумма) никогда не хранится — её всегда считает
вызывающий код (см. app/api/v1/goals.py) как разницу сумм contribution и
withdrawal из GoalEntry, тем же принципом, что уже применяется для баланса
счёта, остатка долга и расходов по бюджету.

Goal.status в БД не хранится как строка "active"/"completed" — статус
всегда выводится заново через calculate_goal_status() (архивность —
единственный факт, который решает пользователь, а не деньги; см.
Goal.is_archived в app/db/models/goal.py). Это тот же приём, что и у
Budget, где статус тоже нигде не кэшируется.
"""

from __future__ import annotations

import enum
from decimal import ROUND_HALF_UP, Decimal

from app.engine.money import Money

__all__ = [
    "GoalStatus",
    "calculate_goal_remaining",
    "calculate_goal_progress",
    "calculate_goal_status",
]


class GoalStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    archived = "archived"


def calculate_goal_remaining(target: Money, saved: Money) -> Money:
    """Остаток до цели. Если накоплено больше цели, до цели больше ничего
    не остаётся — остаток не уходит в отрицательные числа (в отличие от
    остатка бюджета, где перерасход намеренно виден как минус)."""
    remaining = target - saved
    return remaining if remaining.is_positive else Money.zero(target.currency)


def calculate_goal_progress(saved: Money, target: Money) -> Decimal:
    """Процент выполнения для UI, округлённый до 0.1 и ограниченный 100% —
    накопить можно больше цели, но прогресс-бар не должен "переполняться".
    target <= 0 не должен случаться (Goal.target_amount_minor > 0 на
    уровне схемы/БД), но на всякий случай не делим на ноль."""
    if target.minor <= 0:
        return Decimal(100) if saved.minor > 0 else Decimal(0)
    ratio = saved.ratio_to(target) * 100
    capped = min(ratio, Decimal(100))
    return capped.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def calculate_goal_status(saved: Money, target: Money, is_archived: bool) -> GoalStatus:
    """Архивность — решение пользователя и имеет приоритет: архивная цель
    остаётся архивной, даже если формально уже "выполнена" деньгами."""
    if is_archived:
        return GoalStatus.archived
    if target.minor > 0 and saved.minor >= target.minor:
        return GoalStatus.completed
    return GoalStatus.active
