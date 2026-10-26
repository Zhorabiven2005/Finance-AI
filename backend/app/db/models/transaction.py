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
# Назначения операции (Stage 3F). NULL в БД — обычный доход или расход.
TRANSACTION_PURPOSES = ("own_transfer", "external_transfer", "debt_repayment")


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
    # Назначение операции (Stage 3F), задаётся только явным действием
    # пользователя. NULL — обычный доход или расход. Иначе одно из
    # TRANSACTION_PURPOSES: перевод между своими счетами, перевод на свой
    # внешний продукт (счёт или договор вне приложения), погашение долга.
    # Сумма, дата, счёт, категория и комментарий при этом не меняются, баланс
    # счёта тоже (деньги действительно ушли или пришли) — меняется только
    # учёт в доходах и расходах (см. app/engine/flows.py).
    purpose: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Второй свой счёт для перевода между своими счетами. Без внешнего ключа,
    # как у Notification.entity_id: связь проверяется при записи, а удаление
    # счёта или долга не должно трогать саму операцию.
    purpose_account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Долг, который погашает операция (необязательно).
    purpose_debt_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    account: Mapped["Account"] = relationship(back_populates="transactions")
    category: Mapped["Category"] = relationship(back_populates="transactions")
    debt_payment: Mapped["DebtPayment | None"] = relationship(back_populates="transaction")
