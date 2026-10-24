"""Подключение к SQLite и сессии SQLAlchemy."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


def _create_engine() -> Engine:
    settings.db_file.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        settings.database_url,
        # FastAPI обслуживает запросы в пуле потоков, поэтому проверку потока
        # SQLite отключаем: сессия всё равно не разделяется между запросами.
        connect_args={"check_same_thread": False},
        echo=False,
        future=True,
    )


engine = _create_engine()


def configure_sqlite_connection(dbapi_connection) -> None:
    """Настройки SQLite, нужные и продакшн-движку, и тестовому (см.
    tests/conftest.py) — вынесены сюда, чтобы не рассинхронизировать два
    места регистрации.
    """
    cursor = dbapi_connection.cursor()
    # SQLite по умолчанию НЕ проверяет внешние ключи. Для финансовых данных
    # это недопустимо: удаление счёта осиротит транзакции.
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
    # SQLite LIKE регистронезависим только для ASCII (та же причина, по
    # которой раньше пришлось чинить сравнение названий категорий на
    # Python-стороне). Поиск по операциям (Stage 2A) ищет по кириллическим
    # названиям категорий/счетов, поэтому регистрируем Unicode-safe
    # регистронезависимое сравнение прямо в SQLite.
    dbapi_connection.create_function(
        "casefold_unicode", 1, lambda s: s.casefold() if s is not None else None
    )


@event.listens_for(engine, "connect")
def _configure_sqlite(dbapi_connection, _record) -> None:
    configure_sqlite_connection(dbapi_connection)
    cursor = dbapi_connection.cursor()
    # WAL: читатели не блокируют писателя, заметно быстрее на десктопе.
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)


def get_db() -> Generator[Session, None, None]:
    """Зависимость FastAPI: сессия на один запрос."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
