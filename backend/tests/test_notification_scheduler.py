"""Периодическая проверка: устойчивость к ошибкам, остановка, без параллельного запуска."""

from __future__ import annotations

import asyncio
import time

from app.notifications import scheduler, service


def test_failure_does_not_stop_following_checks():
    calls = []

    def flaky():
        calls.append(time.monotonic())
        if len(calls) == 1:
            raise RuntimeError("database is locked")

    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(scheduler.periodic_checks(stop, 0.01, flaky))
        while len(calls) < 3:
            await asyncio.sleep(0.01)
        stop.set()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(scenario())
    assert len(calls) >= 3


def test_stop_event_ends_task_without_waiting_full_interval():
    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(scheduler.periodic_checks(stop, 3600, lambda: None))
        await asyncio.sleep(0.01)
        started = time.monotonic()
        stop.set()
        await asyncio.wait_for(task, timeout=1)
        return time.monotonic() - started

    assert asyncio.run(scenario()) < 0.5


def test_safe_check_reports_failure_instead_of_raising():
    def boom():
        raise ValueError("x")

    assert asyncio.run(scheduler.safe_check(boom)) is False
    assert asyncio.run(scheduler.safe_check(lambda: None)) is True


def test_run_check_once_skips_when_another_check_is_running(monkeypatch):
    opened = []

    class FakeSession:
        def __enter__(self):
            opened.append(1)
            return object()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(scheduler, "SessionLocal", FakeSession)
    assert service._LOCK.acquire(blocking=False)
    try:
        assert scheduler.run_check_once() is None
    finally:
        service._LOCK.release()
    assert opened == [1]
