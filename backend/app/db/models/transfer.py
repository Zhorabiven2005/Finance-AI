"""Перевод между двумя своими счетами.

Перевод — не доход и не расход: у него нет категории, и он не участвует в
статистике доходов/расходов. Он просто уменьшает баланс счёта-источника и
увеличивает баланс счёта-получателя на одну и ту же сумму.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UTCDateTime

if TYPE_CHECKING:
    from app.db.models.account import Account


class Transfer(Base, TimestampMixin):
    __tablename__ = "transfers"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="amount_positive"),
        CheckConstraint(
            "from_account_id != to_account_id", name="distinct_accounts"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    from_account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id"), nullable=False, index=True
    )
    to_account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id"), nullable=False, index=True
    )
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, index=True
    )
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)

    from_account: Mapped["Account"] = relationship(
        back_populates="transfers_out", foreign_keys=[from_account_id]
    )
    to_account: Mapped["Account"] = relationship(
        back_populates="transfers_in", foreign_keys=[to_account_id]
    )
