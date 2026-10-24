"""Бюджет: лимит расходов по категории на календарный месяц.

Фактически потраченная сумма (spent) нигде не хранится — она всегда
выводится заново из Transaction (см. app/api/v1/budgets.py и
app/engine/budgets.py), тем же принципом, что уже применяется для баланса
счёта и остатка долга: кешированное число могло бы разойтись с реальными
операциями, вычисляемое — не может.

Бюджет предназначен для контроля расходов — привязка к income-категории
запрещается на уровне API (Category.type там же проверяется), а не здесь:
это позволяет вернуть понятную ошибку, а не полагаться на CHECK на чужой
таблице, которого SQLite всё равно не умеет выразить.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.category import Category


class Budget(Base, TimestampMixin):
    __tablename__ = "budgets"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="amount_positive"),
        CheckConstraint("month >= 1 AND month <= 12", name="month_valid"),
        UniqueConstraint(
            "category_id", "year", "month", "currency", name="uq_category_period_currency"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id"), nullable=False, index=True
    )
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)

    category: Mapped["Category"] = relationship()
