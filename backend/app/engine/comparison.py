"""Чистые правила сравнения периодов (Stage 3D).

Как и весь app/engine/, без FastAPI и SQLAlchemy: на вход даты, Money и
простые кортежи, на выход — окна периодов, изменения и подозрительные пары.

Окна сравнения (календарные даты UTC, как у бюджетов и инсайтов):
  * текущий месяц — дни 1…N текущего месяца против дней 1…N прошлого месяца
    (N — сегодняшнее число; если в прошлом месяце дней меньше, берётся весь
    прошлый месяц, и это помечается);
  * прошлый месяц — против позапрошлого (полные календарные месяцы);
  * три месяца — три полных месяца против трёх предыдущих.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from app.engine.analytics import percent_change
from app.engine.money import Money

ComparisonKey = Literal["current_month", "previous_month", "last_3_months"]
PercentNullReason = Literal["zero_base", "insufficient_history"]

__all__ = [
    "ComparisonKey",
    "Window",
    "ComparisonWindows",
    "comparison_windows",
    "Change",
    "change",
    "Movement",
    "mirror_pairs",
]


def _prev(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


@dataclass(frozen=True)
class Window:
    """Полуинтервал дат [first, last] включительно."""

    first: date
    last: date

    @property
    def start(self) -> datetime:
        return datetime(self.first.year, self.first.month, self.first.day, tzinfo=timezone.utc)

    @property
    def end(self) -> datetime:
        """Последняя микросекунда дня last (UTC), как у month_bounds."""
        return self.start + timedelta(days=(self.last - self.first).days + 1) - timedelta(microseconds=1)

    @property
    def days(self) -> int:
        return (self.last - self.first).days + 1


@dataclass(frozen=True)
class ComparisonWindows:
    key: ComparisonKey
    current: Window
    previous: Window
    # True — сравниваются одинаковые дни месяцев (неполный текущий месяц).
    same_days: bool
    # Для неполного месяца: в прошлом месяце не нашлось столько же дней.
    previous_shorter: bool = False


def _month(year: int, month: int) -> Window:
    return Window(date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]))


def comparison_windows(key: ComparisonKey, today: date) -> ComparisonWindows:
    if key == "current_month":
        py, pm = _prev(today.year, today.month)
        prev_days = calendar.monthrange(py, pm)[1]
        n = today.day
        return ComparisonWindows(
            key,
            Window(date(today.year, today.month, 1), today),
            Window(date(py, pm, 1), date(py, pm, min(n, prev_days))),
            same_days=True,
            previous_shorter=n > prev_days,
        )
    if key == "previous_month":
        y1, m1 = _prev(today.year, today.month)
        y2, m2 = _prev(y1, m1)
        return ComparisonWindows(key, _month(y1, m1), _month(y2, m2), same_days=False)
    months: list[tuple[int, int]] = []
    y, m = today.year, today.month
    for _ in range(6):
        y, m = _prev(y, m)
        months.append((y, m))  # от новых к старым
    current = Window(_month(*months[2]).first, _month(*months[0]).last)
    previous = Window(_month(*months[5]).first, _month(*months[3]).last)
    return ComparisonWindows("last_3_months", current, previous, same_days=False)


@dataclass(frozen=True)
class Change:
    current: Money
    previous: Money
    delta: Money
    percent: Decimal | None
    percent_null_reason: PercentNullReason | None


def change(current: Money, previous: Money, *, history_ok: bool = True) -> Change:
    """Абсолютное и относительное изменение. Процента нет, если база равна
    нулю («выросли на ∞%» бессмысленно) или прошлый период не покрыт
    данными (процент от неполной базы вводит в заблуждение)."""
    delta = current - previous
    if not history_ok:
        return Change(current, previous, delta, None, "insufficient_history")
    pct = percent_change(current, previous)
    return Change(current, previous, delta, pct, None if pct is not None else "zero_base")


# --- возможные внутренние переводы, записанные как доход и расход ------------------


@dataclass(frozen=True)
class Movement:
    id: int
    account_id: int
    kind: Literal["income", "expense"]
    amount_minor: int
    day: date


def mirror_pairs(movements: list[Movement]) -> list[tuple[Movement, Movement]]:
    """Пары «расход на одном своём счёте + доход той же суммы на другом своём
    счёте в тот же день» (одна валюта — отбирает вызывающий код). Это только
    подозрение: такие операции могут быть переводом между своими счетами,
    записанным как две операции, а могут быть случайным совпадением. Ничего
    не исключается и не переклассифицируется — пары показываются как
    предупреждение. Каждая операция входит не больше чем в одну пару."""
    incomes = sorted((m for m in movements if m.kind == "income"), key=lambda m: (m.day, m.id))
    used: set[int] = set()
    pairs = []
    for out in sorted((m for m in movements if m.kind == "expense"), key=lambda m: (m.day, m.id)):
        for inc in incomes:
            if (
                inc.id not in used
                and inc.amount_minor == out.amount_minor
                and inc.day == out.day
                and inc.account_id != out.account_id
            ):
                used.add(inc.id)
                pairs.append((out, inc))
                break
    return pairs
