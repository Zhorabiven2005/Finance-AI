"""Чистые формулы показателей финансового контекста (Stage 2F).

Как и app/engine/, модуль не зависит ни от FastAPI, ни от SQLAlchemy.
Деньги — только целые минорные единицы одной валюты (Money); проценты и
отношения считаются в Decimal и округляются ROUND_HALF_UP. Формулы, периоды
и причины null описаны в docs/financial-context.md — при изменении формулы
обновляется и документ.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.engine.analytics import percent_change
from app.engine.money import Money, money_sum

PERCENT_STEP = Decimal("0.1")
RATIO_STEP = Decimal("0.01")


def round_percent(value: Decimal | None) -> float | None:
    """Процент с одним знаком после запятой, ROUND_HALF_UP (как в аналитике)."""
    if value is None:
        return None
    return float(value.quantize(PERCENT_STEP, rounding=ROUND_HALF_UP))


def round_ratio(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value.quantize(RATIO_STEP, rounding=ROUND_HALF_UP))


def div_half_up(minor: int, parts: int) -> int:
    """Целочисленное деление с округлением половины от нуля (ROUND_HALF_UP)."""
    if parts <= 0:
        raise ValueError("parts должен быть положительным")
    q, r = divmod(abs(minor), parts)
    if 2 * r >= parts:
        q += 1
    return q if minor >= 0 else -q


def div_ceil(minor: int, parts: int) -> int:
    """Целочисленное деление с округлением вверх (для неотрицательных сумм)."""
    if parts <= 0:
        raise ValueError("parts должен быть положительным")
    return -(-minor // parts)


# --- динамика --------------------------------------------------------------


def expense_change_percent(last: Money, previous: Money) -> tuple[float | None, str | None]:
    """(E_last − E_prev) / E_prev × 100. null, если в предыдущем месяце
    расходов не было: «рост на N%» от нуля бессмыслен."""
    change = percent_change(last, previous)
    if change is None:
        return None, "no_expense_previous_month"
    return round_percent(change), None


@dataclass(frozen=True)
class Average:
    value: Money | None
    null_reason: str | None
    window_months: int
    months_with_transactions: int


def monthly_average(monthly_totals: list[Money], months_with_transactions: int, currency) -> Average:
    """Среднее за окно: Σ / N, где N — ВСЕ месяцы окна (пустые = 0).

    null, если в окне не было ни одной операции этого вида: «ноль в среднем»
    при полном отсутствии истории ввёл бы в заблуждение. months_with_transactions
    позволяет отличить «тратил мало» от «истории ещё нет»."""
    window = len(monthly_totals)
    if window == 0 or months_with_transactions == 0:
        return Average(None, "no_transactions_in_window", window, months_with_transactions)
    # money_sum проверяет, что все суммы — одной валюты.
    total = money_sum(monthly_totals, currency).minor
    return Average(Money.of(div_half_up(total, window), currency), None, window, months_with_transactions)


def savings_rate_percent(income: Money, expense: Money) -> tuple[float | None, str | None]:
    """(I − E) / I × 100; бывает отрицательной. null при нулевом доходе."""
    if income.minor == 0:
        return None, "no_income_last_month"
    rate = Decimal(income.minor - expense.minor) / Decimal(income.minor) * 100
    return round_percent(rate), None


def debt_to_avg_monthly_income(i_owe: Money, avg_income: Money | None) -> tuple[float | None, str | None]:
    """Σ остатков «я должен» / средний месячный доход: во сколько среднемесячных
    доходов обходится долг. Без долгов — 0; без дохода в окне — null."""
    if i_owe.minor == 0:
        return 0.0, None
    if avg_income is None or avg_income.minor <= 0:
        return None, "no_income_in_window"
    return round_ratio(Decimal(i_owe.minor) / Decimal(avg_income.minor)), None


# --- бюджеты ---------------------------------------------------------------


def budget_usage_percent(spent: Money, limit: Money) -> tuple[float | None, str | None]:
    """Σ потраченного / Σ лимитов × 100 по бюджетам одной валюты."""
    if limit.minor == 0:
        return None, "zero_budget_limit"
    return round_percent(Decimal(spent.minor) / Decimal(limit.minor) * 100), None


# --- цели ------------------------------------------------------------------


def months_left(today: date, target_date: date) -> int:
    """Разница календарных месяцев между сегодня и сроком, не меньше 1
    (срок в текущем месяце — значит, остался этот месяц)."""
    diff = (target_date.year - today.year) * 12 + (target_date.month - today.month)
    return max(1, diff)


def goal_plan(
    status: str, remaining: Money, target_date: date | None, today: date
) -> tuple[int | None, Money | None, str | None]:
    """(месяцев до срока, нужный ежемесячный взнос, причина null).

    Взнос = ⌈остаток / месяцев⌉ — округление вверх до минорной единицы, чтобы
    при таком взносе цель точно успевала к сроку."""
    if status == "archived":
        return None, None, "goal_archived"
    if status == "completed":
        return None, None, "goal_completed"
    if target_date is None:
        return None, None, "no_target_date"
    if target_date < today:
        return None, None, "target_date_passed"
    months = months_left(today, target_date)
    return months, Money.of(div_ceil(remaining.minor, months), remaining.currency), None


# --- регулярные операции -----------------------------------------------------


def forecast_date_status(occurs_on: date, today_local: date, today_utc: date) -> str:
    """Статус даты прогноза с учётом того, что обработка регулярных операций
    идёт по дате UTC, а «сегодня» пользователя — локальная дата.

    Неоднозначная дата не выдаётся за подтверждённую просрочку."""
    low, high = min(today_local, today_utc), max(today_local, today_utc)
    if occurs_on > high:
        return "upcoming"
    if occurs_on < low:
        return "past_unprocessed"
    if today_local == today_utc:
        return "due_today"
    return "timezone_ambiguous"
