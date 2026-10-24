"""Расчёт остатка и статуса долга.

Как и баланс счёта (см. app/engine/accounts.py), остаток долга не хранится
отдельным полем — он всегда пересчитывается из суммы долга и истории
погашений, поэтому не может разойтись с фактическими платежами.
"""

from __future__ import annotations

import enum
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

from app.engine.money import Money, money_sum

__all__ = [
    "DEBT_DUE_SOON_DAYS",
    "DebtDueState",
    "DebtStatus",
    "debt_due_state",
    "debt_paid_percent",
    "debt_remaining",
    "debt_status",
]


class DebtStatus(str, enum.Enum):
    active = "active"
    partially_paid = "partially_paid"
    paid = "paid"


def debt_remaining(principal: Money, payments: Iterable[Money]) -> Money:
    """Остаток долга = сумма долга минус сумма погашений.

    payments — положительные суммы платежей в счёт долга.
    """
    paid = money_sum(payments, principal.currency)
    return principal - paid


def debt_status(principal: Money, remaining: Money) -> DebtStatus:
    """Статус долга по остатку.

    remaining <= 0 значит долг погашен полностью (переплата невозможна —
    это проверяется на уровне API при создании платежа).
    """
    if remaining.minor <= 0:
        return DebtStatus.paid
    if remaining.minor < principal.minor:
        return DebtStatus.partially_paid
    return DebtStatus.active


# ---------------------------------------------------------------------------
# Срок погашения (Stage 2E)
# ---------------------------------------------------------------------------

# Срок «скоро» — за сколько дней до даты погашения. Один порог и для
# отображения, и для уведомлений, чтобы UI и уведомления не спорили.
DEBT_DUE_SOON_DAYS = 7


class DebtDueState(str, enum.Enum):
    none = "none"  # срок не задан
    upcoming = "upcoming"  # срок впереди, ещё не скоро
    soon = "soon"  # через 1..DEBT_DUE_SOON_DAYS дней
    today = "today"
    overdue = "overdue"
    paid = "paid"  # долг погашен — срок больше не важен


def debt_due_state(
    due_date: date | None, remaining_minor: int, today: date, soon_days: int = DEBT_DUE_SOON_DAYS
) -> DebtDueState:
    if remaining_minor <= 0:
        return DebtDueState.paid
    if due_date is None:
        return DebtDueState.none
    days = (due_date - today).days
    if days < 0:
        return DebtDueState.overdue
    if days == 0:
        return DebtDueState.today
    if days <= soon_days:
        return DebtDueState.soon
    return DebtDueState.upcoming


def debt_paid_percent(principal: Money, remaining: Money) -> Decimal:
    """Процент погашения, 0..100 с одним знаком (без float)."""
    if principal.minor <= 0:
        return Decimal(0)
    paid = min(max(principal.minor - remaining.minor, 0), principal.minor)
    return (Decimal(paid) * 100 / Decimal(principal.minor)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
