"""Чистые правила финансовых инсайтов (Stage 3C).

Как и весь app/engine/, модуль не зависит ни от FastAPI, ни от SQLAlchemy:
на вход — целые минорные единицы одной валюты и даты, на выход — числа и
решения. Сборка из БД — app/insights/builder.py.

Правила намеренно простые и объяснимые пользователю:
  * «крупный расход» — сравнение с обычным уровнем трат самого пользователя
    (медиана и межквартильный размах), а не просто большая сумма;
  * «регулярный платёж» — не меньше трёх одинаковых списаний с устойчивым
    интервалом (месяц или неделя), а не догадка по названию;
  * темп бюджета — линейная оценка «если тратить так же», только когда
    прошла хотя бы неделя месяца; это оценка, а не прогноз.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

__all__ = [
    "LARGE_EXPENSE_MIN_BASELINE",
    "LargeExpenseThreshold",
    "large_expense_threshold",
    "times_median",
    "Cadence",
    "RECURRING_MIN_OCCURRENCES",
    "detect_cadence",
    "BUDGET_PACE_MIN_DAYS",
    "projected_month_spend",
    "nearest_rank",
]

# Меньше 20 трат — «обычный уровень» не определён: одна-две покупки
# сдвигают медиану, и вывод был бы случайным.
LARGE_EXPENSE_MIN_BASELINE = 20
# Порог: не меньше Q3 + 3·IQR (классическая граница «далёких» значений) и не
# меньше пяти медианных трат — чтобы при очень ровных тратах (IQR ≈ 0) обычная
# покупка чуть дороже среднего не считалась крупной.
LARGE_EXPENSE_IQR_FACTOR = 3
LARGE_EXPENSE_MEDIAN_FACTOR = 5


def nearest_rank(sorted_values: list[int], percent: int) -> int:
    """Перцентиль методом ближайшего ранга — целочисленно, без интерполяции:
    результат всегда одно из реальных значений."""
    if not sorted_values:
        raise ValueError("Пустой набор значений")
    if not 0 < percent <= 100:
        raise ValueError("percent должен быть в (0, 100]")
    rank = -(-percent * len(sorted_values) // 100)  # ⌈p·n/100⌉
    return sorted_values[max(rank, 1) - 1]


@dataclass(frozen=True)
class LargeExpenseThreshold:
    baseline_count: int
    median_minor: int
    q1_minor: int
    q3_minor: int
    threshold_minor: int


def large_expense_threshold(amounts_minor: list[int]) -> LargeExpenseThreshold | None:
    """Порог крупного расхода по тратам одной валюты; None, если трат мало."""
    if len(amounts_minor) < LARGE_EXPENSE_MIN_BASELINE:
        return None
    values = sorted(amounts_minor)
    median = nearest_rank(values, 50)
    q1, q3 = nearest_rank(values, 25), nearest_rank(values, 75)
    threshold = max(q3 + LARGE_EXPENSE_IQR_FACTOR * (q3 - q1), LARGE_EXPENSE_MEDIAN_FACTOR * median)
    return LargeExpenseThreshold(len(values), median, q1, q3, threshold)


def times_median(amount_minor: int, median_minor: int) -> Decimal:
    """Во сколько раз трата больше медианной, с одним знаком (ROUND_HALF_UP)."""
    if median_minor <= 0:
        raise ValueError("Медиана должна быть положительной")
    return (Decimal(amount_minor) / Decimal(median_minor)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


# --- регулярные платежи -----------------------------------------------------------

Cadence = Literal["monthly", "weekly"]
RECURRING_MIN_OCCURRENCES = 3
# Допуск интервалов: месяц 28–31 день плюс сдвиг списания на выходные и
# между банковскими днями; неделя — ±1 день.
_CADENCE_BOUNDS: dict[Cadence, tuple[int, int]] = {"monthly": (26, 35), "weekly": (6, 8)}


def detect_cadence(days: list[date]) -> Cadence | None:
    """Устойчивая периодичность одинаковых списаний: все интервалы между
    соседними датами в границах одного периода. Два списания в один день —
    не регулярность (вероятно, две разные покупки)."""
    if len(days) < RECURRING_MIN_OCCURRENCES:
        return None
    ordered = sorted(days)
    intervals = [(b - a).days for a, b in zip(ordered, ordered[1:])]
    for cadence, (low, high) in _CADENCE_BOUNDS.items():
        if all(low <= i <= high for i in intervals):
            return cadence
    return None


# --- темп бюджета -------------------------------------------------------------------

BUDGET_PACE_MIN_DAYS = 7


def projected_month_spend(spent_minor: int, day_of_month: int, days_in_month: int) -> int | None:
    """Сколько выйдет за месяц, если тратить так же, как с начала месяца:
    ⌈потрачено × дней в месяце / прошедших дней⌉. None в первую неделю —
    по нескольким дням темп ничего не говорит."""
    if day_of_month < BUDGET_PACE_MIN_DAYS or days_in_month <= 0:
        return None
    if day_of_month >= days_in_month:
        return spent_minor
    return -(-spent_minor * days_in_month // day_of_month)
