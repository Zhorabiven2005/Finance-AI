"""Регулярная операция: шаблон/правило, а не запись в журнале.

При наступлении next_run_date правило создаёт обычный Transaction (см.
app/api/v1/recurring_transactions.py) — баланс счёта пересчитывается уже
существующим механизмом (app/api/v1/accounts.py), отдельного пути
изменения баланса здесь нет и не должно быть.

RecurringTransactionRun — защита от повторной генерации: перед созданием
Transaction на дату D роутер проверяет, нет ли уже строки (rule_id, D), и
уникальный индекс гарантирует это на уровне БД, а не только в коде. Список
уже сгенерированных Transaction через это удаётся хранить как аудит, не
трогая саму Transaction — она остаётся обычной, ничем не помеченной
операцией.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.account import Account
    from app.db.models.category import Category

RECURRING_TYPES = ("income", "expense")
RECURRING_FREQUENCIES = ("daily", "weekly", "monthly", "yearly")


class RecurringTransaction(Base, TimestampMixin):
    __tablename__ = "recurring_transactions"
    __table_args__ = (
        CheckConstraint("type IN ('income','expense')", name="type_valid"),
        CheckConstraint("amount_minor > 0", name="amount_positive"),
        CheckConstraint(
            "frequency IN ('daily','weekly','monthly','yearly')", name="frequency_valid"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(10), nullable=False)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id"), nullable=False, index=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id"), nullable=False, index=True
    )
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    frequency: Mapped[str] = mapped_column(String(10), nullable=False)
    next_run_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    account: Mapped["Account"] = relationship()
    category: Mapped["Category"] = relationship()
    runs: Mapped[list["RecurringTransactionRun"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )


class RecurringTransactionRun(Base, TimestampMixin):
    """Один факт генерации: правило rule_id уже создало операцию на дату
    run_date. Существование строки — источник истины для идемпотентности."""

    __tablename__ = "recurring_transaction_runs"
    __table_args__ = (
        UniqueConstraint("recurring_transaction_id", "run_date", name="uq_rule_run_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recurring_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("recurring_transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    # ondelete=CASCADE: сгенерированная Transaction — обычная операция и
    # должна свободно удаляться пользователем, как любая другая (см. модуль
    # docstring). Без каскада DELETE упал бы с ошибкой внешнего ключа — та
    # же категория бага, что уже находилась и чинилась в Stage 1 для
    # DebtPayment.account_id. Удаление этой строки безопасно для
    # идемпотентности: next_run_date правила уже продвинут за эту дату, и
    # pending_occurrences к ней не вернётся.
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False
    )

    rule: Mapped["RecurringTransaction"] = relationship(back_populates="runs")
