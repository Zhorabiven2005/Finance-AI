"""Периодическая проверка уведомлений внутри процесса backend.

Без Celery/Redis: одна asyncio-задача, созданная в lifespan. Свойства:
  * ошибка одной итерации логируется и НЕ останавливает следующие;
  * если предыдущая проверка ещё идёт (или идёт ручная) — итерация
    пропускается, а не встаёт в очередь (см. NotificationCheckBusy);
  * остановка сервера будит задачу через stop_event, и она завершается
    без ожидания полного интервала.

Работает только пока запущен backend: при выключенном или спящем
компьютере проверок нет; после запуска их догонит проверка при старте.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from starlette.concurrency import run_in_threadpool

from app.db.session import SessionLocal
from app.notifications.service import NotificationCheckBusy, generate_notifications

logger = logging.getLogger("app.notifications")


def run_check_once() -> dict[str, int] | None:
    """Одна проверка в собственной сессии; не ждёт, если проверка уже идёт."""
    with SessionLocal() as db:
        try:
            result = generate_notifications(db, wait_seconds=0).as_dict()
        except NotificationCheckBusy:
            logger.info("Проверка уведомлений уже выполняется — пропуск")
            return None
    if result["created"] or result["resolved"]:
        logger.info("Уведомления: %s", result)
    return result


async def safe_check(check: Callable[[], object]) -> bool:
    try:
        await run_in_threadpool(check)
        return True
    except Exception:
        logger.exception("Проверка уведомлений завершилась ошибкой; следующая будет по расписанию")
        return False


async def periodic_checks(
    stop_event: asyncio.Event,
    interval_seconds: float,
    check: Callable[[], object] = run_check_once,
) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            return  # остановка сервера
        except asyncio.TimeoutError:
            pass
        await safe_check(check)
