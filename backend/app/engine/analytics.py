"""Чистая логика финансовой аналитики: гранулярность графика, бакеты
временного ряда, предыдущий период для сравнения, процентное изменение.

Как и весь app/engine/, модуль не зависит ни от FastAPI, ни от SQLAlchemy —
на вход идут простые datetime/Money, а не ORM-объекты или запросы.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from app.engine.money import Money

Granularity = Literal["day", "week", "month"]

__all__ = [
    "Granularity",
    "choose_granularity",
    "bucket_key",
    "generate_buckets",
    "previous_period",
    "percent_change",
    "share_percent",
]

# Пороги подобраны под быстрые периоды UI (Сегодня/7 дней/Этот и прошлый
# месяц/3 месяца/произвольный): до месяца — по дням, до ~4 месяцев — по
# неделям, длиннее — по месяцам. Так график никогда не рисует сотни точек.
#
# 32, а не 31: frontend считает границы периода в локальной полуночи
# браузера и переводит их в UTC (см. lib/period.ts). При положительном
# смещении часового пояса локальная полночь 1-го числа уходит в UTC ещё
# на предыдущие сутки, из-за чего "месяц" длиной ровно в 31 календарный
# день иногда выглядит как 32 UTC-дня — с порогом 31 это несправедливо
# толкнуло бы обычный месяц на недельную гранулярность.
_DAY_GRANULARITY_MAX_SPAN = 32
_WEEK_GRANULARITY_MAX_SPAN = 120


def choose_granularity(date_from: datetime, date_to: datetime) -> Granularity:
    span_days = (date_to.date() - date_from.date()).days + 1
    if span_days <= _DAY_GRANULARITY_MAX_SPAN:
        return "day"
    if span_days <= _WEEK_GRANULARITY_MAX_SPAN:
        return "week"
    return "month"


def bucket_key(occurred_at: datetime, granularity: Granularity) -> date:
    """Дата начала бакета, в который попадает операция.

    Бакетирование идёт по календарной дате UTC (occurred_at уже
    UTC-aware — см. app/db/base.py:UTCDateTime), без пересчёта в локальный
    часовой пояс пользователя: backend его не знает. Это тот же принцип,
    что уже использует dashboard.py для "текущего месяца".
    """
    d = occurred_at.date()
    if granularity == "day":
        return d
    if granularity == "week":
        iso_year, iso_week, _ = d.isocalendar()
        return date.fromisocalendar(iso_year, iso_week, 1)
    return date(d.year, d.month, 1)


def generate_buckets(date_from: datetime, date_to: datetime, granularity: Granularity) -> list[date]:
    """Полный ряд дат начала бакетов на весь период, включая пустые.

    Нужен, чтобы график динамики был равномерным по оси времени — без
    этого день без операций просто выпал бы из ряда, и линия соединила бы
    несмежные точки, искажая картину.
    """
    start = bucket_key(date_from, granularity)
    end = bucket_key(date_to, granularity)
    buckets: list[date] = []
    current = start
    while current <= end:
        buckets.append(current)
        if granularity == "day":
            current += timedelta(days=1)
        elif granularity == "week":
            current += timedelta(weeks=1)
        else:
            current = date(current.year + (current.month // 12), current.month % 12 + 1, 1)
    return buckets


def previous_period(date_from: datetime, date_to: datetime) -> tuple[datetime, datetime]:
    """Непосредственно предшествующий период той же длины, без пересечения."""
    duration = date_to - date_from
    previous_to = date_from - timedelta(microseconds=1)
    previous_from = previous_to - duration
    return previous_from, previous_to


def percent_change(current: Money, previous: Money) -> Decimal | None:
    """Изменение current относительно previous, в процентах.

    None, если процент посчитать нельзя (предыдущее значение — ноль):
    "выросли на N%" бессмысленно, когда раньше было 0."""
    if previous.minor == 0:
        return None
    ratio = current.ratio_to(previous)
    return (ratio - 1) * 100


def share_percent(amount: Money, total: Money) -> Decimal:
    """Доля amount от total, в процентах. 0, если total — ноль (делить не на что)."""
    if total.minor == 0:
        return Decimal(0)
    return amount.ratio_to(total) * 100
