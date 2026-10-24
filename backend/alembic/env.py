"""Окружение Alembic.

URL базы берётся из app.config, а не из alembic.ini, чтобы был один источник
истины. render_as_batch обязателен для SQLite: он не умеет ALTER TABLE,
и Alembic эмулирует изменения через пересоздание таблицы.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, event, pool

from app.config import settings
from app.db.base import Base
import app.db.models  # noqa: F401  — регистрирует модели в метадате

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    settings.db_file.parent.mkdir(parents=True, exist_ok=True)
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    # Прагму включаем через событие подключения, а не выполнением на
    # connection напрямую: прямой exec_driver_sql() до context.configure()
    # неявно открывает транзакцию SQLAlchemy, которую Alembic на SQLite
    # считает уже управляемой извне и не коммитит сам — из-за этого
    # alembic_version никогда не записывался.
    @event.listens_for(connectable, "connect")
    def _configure_sqlite(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
