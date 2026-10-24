"""Счета: банковские, наличные и прочие денежные счета.

Текущий баланс не хранится отдельным столбцом — он вычисляется из
initial_balance_minor и связанных операций (см. app/engine/accounts.py и
app/api/v1/accounts.py). Это архитектурное решение, а не недосмотр: оно
исключает целый класс багов, при которых кешированный баланс расходится с
историей операций после редактирования или удаления транзакции.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.transaction import Transaction
    from app.db.models.transfer import Transfer

ACCOUNT_TYPES = ("bank", "cash", "other")


class Account(Base, TimestampMixin):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            "type IN ('bank','cash','other')", name="type_valid"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    initial_balance_minor: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Без каскадного удаления: счёт с операциями нельзя удалить (см.
    # app/api/v1/accounts.py), поэтому ORM-каскад здесь не нужен и мог бы
    # случайно стереть историю операций при ошибке в коде.
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")
    transfers_out: Mapped[list["Transfer"]] = relationship(
        back_populates="from_account",
        foreign_keys="Transfer.from_account_id",
    )
    transfers_in: Mapped[list["Transfer"]] = relationship(
        back_populates="to_account",
        foreign_keys="Transfer.to_account_id",
    )
