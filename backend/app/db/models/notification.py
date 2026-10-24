"""Уведомления: одна таблица на все типы.

Жизненный цикл строки:
  * создаётся notification engine (app/notifications/service.py) один раз
    на событие — dedup_key уникален;
  * read_at — пользователь прочитал;
  * resolved_at — условие больше не выполняется (долг погашен, срок
    перенесён, бюджет снова в норме): уведомление остаётся в истории как
    неактуальное и не считается непрочитанным;
  * deleted_at — пользователь удалил. Удаление мягкое: строка с ключом
    остаётся и не даёт engine создать то же событие заново.

Ссылка на сущность (entity_type/entity_id) — намеренно без внешнего ключа:
уведомление переживает удаление долга или бюджета.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime

NOTIFICATION_TYPES = (
    "debt_due",
    "debt_overdue",
    "budget_warning",
    "budget_exceeded",
    "spending_increased",
    "recurring_transaction_due",
    "recurring_transaction_missed",
    "system",
)
NOTIFICATION_SEVERITIES = ("info", "warning", "danger")
NOTIFICATION_ENTITY_TYPES = ("debt", "budget", "recurring_transaction", "analytics")


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("severity IN ('info','warning','danger')", name="severity_valid"),
        Index("ix_notifications_active", "deleted_at", "resolved_at", "read_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Тип не ограничен CHECK-ом: список расширяемый, допустимые значения —
    # NOTIFICATION_TYPES (проверяются в коде и в валидаторе backup).
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dedup_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    # JSON-текст: суммы в minor units + валюта, даты. Только для отображения.
    data: Mapped[str | None] = mapped_column(Text, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
