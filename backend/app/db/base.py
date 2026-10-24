"""Декларативная база SQLAlchemy и общие соглашения по именованию.

Явные имена ограничений обязательны для SQLite: без них Alembic не сможет
менять схему через batch-режим, потому что автосгенерированные имена
ограничений неизвестны.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """DateTime(timezone=True), которому можно доверять на SQLite.

    Драйвер SQLite не хранит tzinfo — значение уезжает и приходит обратно
    "наивным", то есть в JSON-ответе API пропадает суффикс "Z"/"+00:00".
    Клиент (new Date() в браузере) в этом случае трактует время как
    локальное, а не UTC, и показывает операции со сдвигом на часовой пояс
    пользователя. Этот тип гарантирует UTC на обеих границах: при записи
    приводит к UTC, при чтении навешивает tzinfo=UTC обратно.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Технические метки времени записи.

    Не путать с датой финансового события: та хранится отдельно как локальная
    дата, чтобы платёж первого числа не уезжал в предыдущий месяц.
    """

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
