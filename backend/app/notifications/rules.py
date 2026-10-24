"""Правила уведомлений — чистые функции без БД и FastAPI.

На вход — уже собранные факты (долги, бюджеты, расходы, правила) и
«сегодня», на выход — кандидаты в уведомления. Каждый кандидат несёт
стабильный dedup_key: ОДНО событие = ОДИН ключ. Ключ всегда начинается с
типа уведомления, затем id сущности и дата/период события.

Горизонт ограничен намеренно, чтобы первый запуск на старых данных не
порождал лавину: бюджеты — только текущий месяц; расходы — только последний
завершённый месяц; у долга — одно состояние срока; у регулярной операции —
только её ближайшая дата.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.engine.budgets import WARNING_THRESHOLD_PERCENT, calculate_budget_status, BudgetStatus
from app.engine.debts import DEBT_DUE_SOON_DAYS, DebtDueState, debt_due_state
from app.engine.money import Money

# Пороговые значения (см. тесты tests/test_notification_rules.py).
RECURRING_DUE_SOON_DAYS = 2
SPENDING_INCREASE_THRESHOLD_PERCENT = 30
BUDGET_WARNING_PERCENT = WARNING_THRESHOLD_PERCENT  # 80, общий с бюджетами
RETENTION_DAYS = 90

T_DEBT_DUE = "debt_due"
T_DEBT_OVERDUE = "debt_overdue"
T_BUDGET_WARNING = "budget_warning"
T_BUDGET_EXCEEDED = "budget_exceeded"
T_SPENDING_INCREASED = "spending_increased"
T_RECURRING_DUE = "recurring_transaction_due"
T_RECURRING_MISSED = "recurring_transaction_missed"
T_SYSTEM = "system"

# Типы, которыми управляет engine (создаёт и закрывает как неактуальные).
ENGINE_TYPES = (
    T_DEBT_DUE,
    T_DEBT_OVERDUE,
    T_BUDGET_WARNING,
    T_BUDGET_EXCEEDED,
    T_SPENDING_INCREASED,
    T_RECURRING_DUE,
    T_RECURRING_MISSED,
)


@dataclass(frozen=True)
class Candidate:
    type: str
    severity: str
    title: str
    message: str
    dedup_key: str
    entity_type: str | None = None
    entity_id: int | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DebtFact:
    id: int
    name: str
    direction: str
    remaining: Money
    due_date: date | None


@dataclass(frozen=True)
class BudgetFact:
    id: int
    category_name: str
    year: int
    month: int
    amount: Money
    spent: Money


@dataclass(frozen=True)
class RecurringFact:
    id: int
    name: str
    type: str
    amount: Money
    next_run_date: date
    end_date: date | None
    is_active: bool


def _money(m: Money) -> dict[str, Any]:
    return {"minor": m.minor, "currency": m.currency.code}


def _ru_date(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def _days_word(n: int) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} день"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} дня"
    return f"{n} дней"


def month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


# ---------------------------------------------------------------------------
# Долги
# ---------------------------------------------------------------------------


def debt_candidates(debts: list[DebtFact], today: date) -> list[Candidate]:
    out = []
    for d in debts:
        state = debt_due_state(d.due_date, d.remaining.minor, today, DEBT_DUE_SOON_DAYS)
        if state not in (DebtDueState.soon, DebtDueState.today, DebtDueState.overdue):
            continue
        assert d.due_date is not None
        what = f"Долг «{d.name}»" if d.direction == "i_owe" else f"Долг вам от «{d.name}»"
        data = {"remaining": _money(d.remaining), "due_date": d.due_date.isoformat(), "direction": d.direction}
        rest = f"Остаток {d.remaining.format()}."
        if state is DebtDueState.overdue:
            days = (today - d.due_date).days
            out.append(
                Candidate(
                    T_DEBT_OVERDUE, "danger", "Долг просрочен",
                    f"{what}: срок был {_ru_date(d.due_date)} ({_days_word(days)} назад). {rest}",
                    f"{T_DEBT_OVERDUE}:{d.id}:{d.due_date.isoformat()}", "debt", d.id, data,
                )
            )
        elif state is DebtDueState.today:
            out.append(
                Candidate(
                    T_DEBT_DUE, "warning", "Срок долга сегодня",
                    f"{what}: срок погашения сегодня, {_ru_date(d.due_date)}. {rest}",
                    f"{T_DEBT_DUE}:{d.id}:{d.due_date.isoformat()}:today", "debt", d.id, data,
                )
            )
        else:
            days = (d.due_date - today).days
            out.append(
                Candidate(
                    T_DEBT_DUE, "info", "Скоро срок долга",
                    f"{what}: срок погашения {_ru_date(d.due_date)}, через {_days_word(days)}. {rest}",
                    f"{T_DEBT_DUE}:{d.id}:{d.due_date.isoformat()}:soon", "debt", d.id, data,
                )
            )
    return out


# ---------------------------------------------------------------------------
# Бюджеты (только текущий месяц)
# ---------------------------------------------------------------------------


def budget_candidates(budgets: list[BudgetFact], today: date) -> list[Candidate]:
    out = []
    for b in budgets:
        if (b.year, b.month) != (today.year, today.month):
            continue
        status = calculate_budget_status(b.spent, b.amount)
        period = month_key(b.year, b.month)
        data = {"spent": _money(b.spent), "amount": _money(b.amount), "period": period}
        # Превышение и «близко к лимиту» взаимоисключающие: при > 100% активен
        # только ключ budget_exceeded, а budget_warning того же месяца engine
        # закроет как неактуальный.
        if status is BudgetStatus.exceeded:
            over = b.spent - b.amount
            out.append(
                Candidate(
                    T_BUDGET_EXCEEDED, "danger", "Бюджет превышен",
                    f"«{b.category_name}»: потрачено {b.spent.format()} из {b.amount.format()}, "
                    f"превышение {over.format()}.",
                    f"{T_BUDGET_EXCEEDED}:{b.id}:{period}", "budget", b.id, data,
                )
            )
        elif status is BudgetStatus.warning:
            out.append(
                Candidate(
                    T_BUDGET_WARNING, "warning", "Бюджет почти исчерпан",
                    f"«{b.category_name}»: потрачено {b.spent.format()} из {b.amount.format()} "
                    f"(не меньше {BUDGET_WARNING_PERCENT}%).",
                    f"{T_BUDGET_WARNING}:{b.id}:{period}", "budget", b.id, data,
                )
            )
    return out


# ---------------------------------------------------------------------------
# Рост расходов: последний завершённый месяц против предыдущего, по валютам
# ---------------------------------------------------------------------------


def spending_candidates(
    expenses: dict[tuple[str, int, int], Money], today: date
) -> list[Candidate]:
    """expenses: (валюта, год, месяц) -> сумма расходов за месяц."""
    last_y, last_m = previous_month(today.year, today.month)
    prev_y, prev_m = previous_month(last_y, last_m)
    out = []
    currencies = sorted({cur for (cur, _, _) in expenses})
    for cur in currencies:
        last = expenses.get((cur, last_y, last_m))
        prev = expenses.get((cur, prev_y, prev_m))
        # Нет предыдущего периода — сравнивать не с чем, уведомления нет.
        if last is None or prev is None or prev.minor <= 0:
            continue
        # Целочисленное сравнение: last >= prev * (1 + порог/100).
        if last.minor * 100 < prev.minor * (100 + SPENDING_INCREASE_THRESHOLD_PERCENT):
            continue
        growth = (Decimal(last.minor - prev.minor) * 100 / Decimal(prev.minor)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        period = month_key(last_y, last_m)
        out.append(
            Candidate(
                T_SPENDING_INCREASED, "warning", "Расходы выросли",
                f"Расходы в {cur} за {last_m:02d}.{last_y}: {last.format()} — на {growth}% больше, "
                f"чем за {prev_m:02d}.{prev_y} ({prev.format()}).",
                f"{T_SPENDING_INCREASED}:{cur}:{period}", "analytics", None,
                {"currency": cur, "period": period, "current": _money(last), "previous": _money(prev),
                 "growth_percent": int(growth)},
            )
        )
    return out


# ---------------------------------------------------------------------------
# Регулярные операции
# ---------------------------------------------------------------------------


def recurring_candidates(rules: list[RecurringFact], today: date) -> list[Candidate]:
    out = []
    for r in rules:
        if not r.is_active:
            continue
        if r.end_date is not None and r.next_run_date > r.end_date:
            continue
        days = (r.next_run_date - today).days
        if days > RECURRING_DUE_SOON_DAYS:
            continue
        sign = "+" if r.type == "income" else "−"
        data = {"amount": _money(r.amount), "next_run_date": r.next_run_date.isoformat(), "type": r.type}
        when = _ru_date(r.next_run_date)
        if days < 0:
            out.append(
                Candidate(
                    T_RECURRING_MISSED, "warning", "Регулярная операция не проведена",
                    f"«{r.name}» ({sign}{r.amount.format()}) должна была пройти {when}. "
                    "Проведите её на странице «Регулярные».",
                    f"{T_RECURRING_MISSED}:{r.id}:{r.next_run_date.isoformat()}",
                    "recurring_transaction", r.id, data,
                )
            )
        else:
            text = "сегодня" if days == 0 else f"через {_days_word(days)}, {when}"
            out.append(
                Candidate(
                    T_RECURRING_DUE, "info", "Скоро регулярная операция",
                    f"«{r.name}» ({sign}{r.amount.format()}) — {text}.",
                    f"{T_RECURRING_DUE}:{r.id}:{r.next_run_date.isoformat()}",
                    "recurring_transaction", r.id, data,
                )
            )
    return out
