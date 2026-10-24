"""Настройки приложения, хранимые в базе.

Единственная строка с id = 1. Здесь живут параметры, привязанные к данным
пользователя (базовая валюта), в отличие от .env, где лежат параметры запуска.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, Session

from app.db.base import Base, TimestampMixin

SINGLETON_ID = 1


class AppSettings(Base, TimestampMixin):
    __tablename__ = "app_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, default=SINGLETON_ID)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="ru-RU")


def get_base_currency(db: Session) -> str:
    """Базовая валюта пользователя: строка ещё не проинициализирована при
    первом запуске до применения миграций, поэтому запасной вариант — из
    .env (см. app/main.py:ensure_app_settings). Используется везде, где
    нужно свести суммы к одной валюте (dashboard, analytics) — MVP не
    конвертирует между валютами."""
    row = db.get(AppSettings, SINGLETON_ID)
    if row is not None:
        return row.base_currency
    from app.config import settings as cfg

    return cfg.base_currency
