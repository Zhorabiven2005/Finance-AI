"""Долги: кто кому должен.

Намеренно отдельная сущность, а не тип счёта — долг не является деньгами,
которыми можно расплатиться, и не должен попадать в списки банковских
счетов. status и remaining не хранятся: они всегда выводятся из principal и
истории DebtPayment (см. app/engine/debts.py), по той же причине, что и
баланс счёта — так их невозможно рассинхронизировать с платежами.

direction:
  * i_owe       — я должен counterparty_name;
  * owed_to_me  — counterparty_name должен мне.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UTCDateTime

if TYPE_CHECKING:
    from app.db.models.account import Account
    from app.db.models.transaction import Transaction

DEBT_DIRECTIONS = ("i_owe", "owed_to_me")


class Debt(Base, TimestampMixin):
    __tablename__ = "debts"
    __table_args__ = (
        CheckConstraint(
            "direction IN ('i_owe','owed_to_me')", name="direction_valid"
        ),
        CheckConstraint("principal_minor > 0", name="principal_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    counterparty_name: Mapped[str] = mapped_column(String(200), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    principal_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)

    payments: Mapped[list["DebtPayment"]] = relationship(
        back_populates="debt", cascade="all, delete-orphan"
    )


class DebtPayment(Base, TimestampMixin):
    __tablename__ = "debt_payments"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="amount_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    debt_id: Mapped[int] = mapped_column(
        ForeignKey("debts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Необязательная связь со счётом: если указана, платёж порождает
    # связанную Transaction (см. app/api/v1/debts.py), и именно она меняет
    # баланс счёта. Долг при этом остаётся отдельной сущностью.
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True
    )
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    paid_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)

    debt: Mapped["Debt"] = relationship(back_populates="payments")
    account: Mapped["Account | None"] = relationship()
    # Движение денег по счёту (если платёж привязан к счёту). Баланс счёта
    # считается ТОЛЬКО по Transaction, а не по DebtPayment — поэтому платёж
    # физически не может уменьшить счёт дважды.
    transaction: Mapped["Transaction | None"] = relationship(
        back_populates="debt_payment", cascade="all, delete-orphan", uselist=False
    )
