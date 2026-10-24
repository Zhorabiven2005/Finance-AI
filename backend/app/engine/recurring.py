"""Чистая логика регулярных операций: следующая дата по расписанию и список
пропущенных дат к обработке.

Как и весь app/engine/, модуль не знает про Transaction/RecurringTransaction
как ORM-сущности — только про даты и частоту. Оркестрация (создание
Transaction, идемпотентность через RecurringTransactionRun) живёт в
app/api/v1/recurring_transactions.py, как dashboard.py уже оркестрирует
несколько запросов поверх чистых функций engine.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

__all__ = ["Frequency", "MAX_OCCURRENCES_PER_RUN", "next_occurrence", "pending_occurrences"]

Frequency = Literal["daily", "weekly", "monthly", "yearly"]

# Защита от бесконечного/неадекватно длинного цикла, если next_run_date по
# ошибке оказался в далёком прошлом (повреждённые данные, ручная правка БД
# и т.п.) — см. п.14 ТЗ. 366 с запасом покрывает "не запускали год".
MAX_OCCURRENCES_PER_RUN = 366


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return (date(year + 1, 1, 1) - date(year, 12, 1)).days
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def _add_months(d: date, months: int) -> date:
    """Прибавляет months к дате, зажимая день в границы получившегося месяца
    (31 января + 1 месяц = 28/29 февраля, а не ошибка). После такого
    сдвига "якорь" дня месяца может уменьшиться и не восстановится в
    последующих более длинных месяцах — сознательное упрощение для MVP,
    расширяемое в будущем без изменения сигнатуры функции."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, _days_in_month(year, month))
    return date(year, month, day)


def next_occurrence(current: date, frequency: Frequency) -> date:
    """Дата следующего срабатывания после current."""
    if frequency == "daily":
        return current + timedelta(days=1)
    if frequency == "weekly":
        return current + timedelta(weeks=1)
    if frequency == "monthly":
        return _add_months(current, 1)
    return _add_months(current, 12)  # yearly


def pending_occurrences(
    next_run_date: date,
    current_date: date,
    frequency: Frequency,
    end_date: date | None,
    max_occurrences: int = MAX_OCCURRENCES_PER_RUN,
) -> tuple[list[date], date, bool]:
    """Даты к генерации (next_run_date, ..., <= current_date), новый
    next_run_date и флаг "правило остаётся активным после этого запуска".

    Даты после end_date не включаются, и правило деактивируется. Список
    ограничен max_occurrences — если данные повреждены (next_run_date в
    далёком прошлом), функция не уйдёт в фактически бесконечный цикл.
    """
    occurrences: list[date] = []
    cursor = next_run_date
    while cursor <= current_date and len(occurrences) < max_occurrences:
        if end_date is not None and cursor > end_date:
            break
        occurrences.append(cursor)
        cursor = next_occurrence(cursor, frequency)

    still_active = end_date is None or cursor <= end_date
    return occurrences, cursor, still_active
