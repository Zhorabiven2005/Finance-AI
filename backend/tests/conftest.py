"""Общие фикстуры тестов.

Тесты, которые создают данные (счета, операции, долги), НЕ должны трогать
backend/data/finance.db — рабочую базу пользователя. Каждый тест получает
собственную SQLite-базу в памяти, поднятую напрямую из ORM-метадаты
(Base.metadata.create_all), без запуска Alembic — так тест быстрее и не
зависит от файловой системы.

Дополнительная страховка — ниже, до импорта приложения: рабочий движок
(app.db.session.engine) направлен в пустой временный каталог, так что даже
случайное обращение к engine/SessionLocal из тестов не дойдёт до рабочей БД.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from collections.abc import Generator

# --- изоляция от рабочей БД ---------------------------------------------------
# Должно выполниться ДО первого импорта app.*: app.config читает DATABASE_PATH
# при импорте, а app.db.session сразу создаёт движок. Переменная окружения
# приоритетнее backend/.env. Файл БД в этом каталоге появится, только если
# что-то действительно подключится к рабочему движку; каталог удаляется при
# завершении процесса тестов.
ISOLATED_DB_DIR = tempfile.mkdtemp(prefix="finance-ai-tests-")
os.environ["DATABASE_PATH"] = os.path.join(ISOLATED_DB_DIR, "must-not-be-used.db")
atexit.register(shutil.rmtree, ISOLATED_DB_DIR, ignore_errors=True)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.db.models  # noqa: F401,E402 — регистрирует все модели в Base.metadata
from app.db.base import Base  # noqa: E402
from app.db.seed import ensure_default_categories  # noqa: E402
from app.db.session import configure_sqlite_connection, get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _configure(dbapi_connection, _record) -> None:
        configure_sqlite_connection(dbapi_connection)

    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    # Без `with`: контекстный менеджер TestClient запускает lifespan
    # приложения, а ensure_app_settings()/ensure_categories() в нём пишут
    # через SessionLocal напрямую в реальный backend/data/finance.db, в
    # обход dependency_overrides. Тестам нужна полная изоляция от рабочей
    # базы, поэтому lifespan здесь не запускается — недостающие категории
    # тест сам добавляет через фикстуру seeded_client.
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def seeded_client(client: TestClient, db_session: Session) -> TestClient:
    """Клиент с заполненным базовым набором категорий."""
    ensure_default_categories(db_session)
    return client
