"""Финансовая цель: планировочная сущность, независимая от счетов.

Накопленная сумма нигде не хранится — она всегда выводится заново из
GoalEntry (см. app/api/v1/goals.py и app/engine/goals.py), тем же
принципом, что уже применяется для баланса счёта и остатка долга.

Добавление GoalEntry НЕ меняет баланс Account — это сознательное решение
Stage 2C: цель и счёт существуют независимо, привязка к реальным деньгам
на счету — материал для будущего этапа, не этого.

is_archived, а не строковый статус-столбец: активность/выполненность цели
полностью выводится из накопленной суммы (см. engine/goals.py), а
единственный факт, который реально нужно ЗАПОМНИТЬ — это то, что
пользователь сознательно отправил цель в архив.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UTCDateTime

GOAL_ENTRY_TYPES = ("contribution", "withdrawal")


class Goal(Base, TimestampMixin):
    __tablename__ = "goals"
    __table_args__ = (
        CheckConstraint("target_amount_minor > 0", name="target_amount_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    target_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    entries: Mapped[list["GoalEntry"]] = relationship(
        back_populates="goal", cascade="all, delete-orphan"
    )


class GoalEntry(Base, TimestampMixin):
    """Один факт движения к цели. currency отдельно не хранится — запись
    всегда в валюте родительской цели (см. docstring модуля), поэтому
    "GoalEntry в другой валюте" структурно невозможно, а не просто
    проверяется на входе."""

    __tablename__ = "goal_entries"
    __table_args__ = (
        CheckConstraint("type IN ('contribution','withdrawal')", name="type_valid"),
        CheckConstraint("amount_minor > 0", name="amount_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(
        ForeignKey("goals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)

    goal: Mapped["Goal"] = relationship(back_populates="entries")
