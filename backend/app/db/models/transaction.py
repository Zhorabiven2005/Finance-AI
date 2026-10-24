"""Доходы и расходы по счёту.

amount_minor всегда положителен — знак операции определяется полем type,
а не знаком суммы. Так проще валидировать ввод и читать данные напрямую
из базы.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UTCDateTime

if TYPE_CHECKING:
    from app.db.models.account import Account
    from app.db.models.category import Category
    from app.db.models.debt import DebtPayment

TRANSACTION_TYPES = ("income", "expense")


class Transaction(Base, TimestampMixin):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("type IN ('income','expense')", name="type_valid"),
        CheckConstraint("amount_minor > 0", name="amount_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id"), nullable=False, index=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(10), nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, index=True
    )
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Если задано — операция является движением денег от погашения долга и
    # принадлежит этому платежу: создаётся, меняется и удаляется только вместе
    # с ним (см. app/api/v1/debts.py). Уникальность гарантирует "один платёж —
    # одна операция" на уровне БД, поэтому задвоить движение нельзя.
    debt_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("debt_payments.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
    )

    account: Mapped["Account"] = relationship(back_populates="transactions")
    category: Mapped["Category"] = relationship(back_populates="transactions")
    debt_payment: Mapped["DebtPayment | None"] = relationship(back_populates="transaction")
