"""Единый источник «сегодня» для сроков и уведомлений.

Приложение локальное: пользователь думает своими сутками, поэтому берётся
локальная дата машины, а не UTC. Вынесено в функцию, чтобы тесты могли
подменять дату (monkeypatch app.clock.today).

utc_today() — дата по UTC. Она нужна только там, где надо честно показать
расхождение с локальной датой: обработка регулярных операций
(POST /recurring-transactions/process) использует дату UTC, и финансовый
контекст (Stage 2F) помечает такие даты как неоднозначные, а не выдаёт их
за подтверждённую просрочку.
"""

from __future__ import annotations

from datetime import date, datetime, timezone


def today() -> date:
    return date.today()


def utc_today() -> date:
    return datetime.now(timezone.utc).date()
