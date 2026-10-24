"""Категории доходов и расходов.

Базовый набор создаётся один раз при первом запуске (см. app/db/seed.py,
тот же приём, что и для AppSettings в app/main.py). Пользователь может
добавлять собственные категории поверх базовых — они отличаются флагом
is_default.

parent_id: дерево категорий ограничено глубиной в один уровень (категория
→ подкатегория, без внуков) — проверка в app/api/v1/categories.py, не
здесь: SQLite не умеет выразить "у родителя нет своего родителя" через
CHECK на той же таблице.

is_archived (Stage 2C): архивная категория остаётся у исторических
Transaction, но не предлагается при создании новых операций/бюджетов/
регулярных операций (см. include_archived в list_categories).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.transaction import Transaction

CATEGORY_TYPES = ("income", "expense")


class Category(Base, TimestampMixin):
    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint("type IN ('income','expense')", name="type_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(10), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    parent: Mapped["Category | None"] = relationship(
        remote_side="Category.id", back_populates="children"
    )
    children: Mapped[list["Category"]] = relationship(back_populates="parent")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="category")
