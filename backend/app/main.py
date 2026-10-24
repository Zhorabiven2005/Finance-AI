"""Точка входа FastAPI.

Слой намеренно тонкий: сборка приложения, CORS, подключение роутеров.
Бизнес-логики здесь нет и быть не должно.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect

from app.api.v1 import api_router
from app.config import settings
from app.db.models import AppSettings, Category
from app.db.models.app_settings import SINGLETON_ID
from app.db.seed import ensure_default_categories
from app.db.session import SessionLocal, engine
from app.engine.money import MoneyError
from app.db.models import Notification
from app.notifications.scheduler import periodic_checks, run_check_once, safe_check

logger = logging.getLogger("app")


def ensure_app_settings() -> None:
    """Создаёт единственную строку настроек при первом запуске.

    Работает только если миграции уже применены. Если таблицы нет,
    молча выходим — пользователь увидит это в /health.
    """
    if not inspect(engine).has_table(AppSettings.__tablename__):
        logger.warning(
            "Таблица app_settings отсутствует. Выполните: alembic upgrade head"
        )
        return
    with SessionLocal() as db:
        if db.get(AppSettings, SINGLETON_ID) is None:
            db.add(
                AppSettings(
                    id=SINGLETON_ID,
                    base_currency=settings.base_currency,
                    locale="ru-RU",
                )
            )
            db.commit()
            logger.info("Настройки инициализированы: %s", settings.base_currency)


def ensure_categories() -> None:
    """Заполняет базовый набор категорий при первом запуске (см. app/db/seed.py)."""
    if not inspect(engine).has_table(Category.__tablename__):
        return
    with SessionLocal() as db:
        ensure_default_categories(db)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("База данных: %s", settings.db_file)
    ensure_app_settings()
    ensure_categories()

    stop_event = asyncio.Event()
    task: asyncio.Task | None = None
    if inspect(engine).has_table(Notification.__tablename__):
        await safe_check(run_check_once)  # при старте backend
        interval = settings.notifications_check_interval_minutes
        if interval > 0:
            task = asyncio.create_task(periodic_checks(stop_event, interval * 60))
    try:
        yield
    finally:
        stop_event.set()
        if task is not None:
            await task


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    # X-Total-Count (пагинация операций, Stage 2A) — по умолчанию браузер
    # не даёт JS читать кастомные заголовки ответа, даже с тем же origin
    # через прокси Vite, если они явно не разрешены здесь.
    expose_headers=["X-Total-Count"],
)

app.include_router(api_router)


@app.exception_handler(MoneyError)
async def money_error_handler(_: Request, exc: MoneyError) -> JSONResponse:
    """Ошибки денежного типа (валютное несоответствие и т.п.) — это всегда
    ошибка запроса клиента, а не сервера."""
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"app": settings.app_name, "docs": "/docs", "health": "/api/v1/health"}
