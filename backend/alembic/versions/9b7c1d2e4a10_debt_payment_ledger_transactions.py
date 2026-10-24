"""debt payments become ledger transactions

Платёж по долгу, привязанный к счёту, теперь представлен одной связанной
Transaction (transactions.debt_payment_id). Баланс счёта читает только
transactions, поэтому существующие платежи со счётом переносятся в журнал
здесь же — иначе после обновления они перестали бы влиять на баланс.

Revision ID: 9b7c1d2e4a10
Revises: 24328f840efc
Create Date: 2026-10-06 12:00:00.000000
"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.db.base


revision: str = '9b7c1d2e4a10'
down_revision: Union[str, None] = '24328f840efc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEDGER_CATEGORY = {
    "i_owe": ("Погашение долга", "expense"),
    "owed_to_me": ("Возврат долга", "income"),
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


def _category_id(bind, direction: str) -> int:
    name, type_ = LEDGER_CATEGORY[direction]
    row = bind.execute(
        sa.text(
            "SELECT id FROM categories WHERE name = :n AND type = :t "
            "ORDER BY is_default DESC, id LIMIT 1"
        ),
        {"n": name, "t": type_},
    ).first()
    if row is not None:
        return row[0]
    now = _now()
    bind.execute(
        sa.text(
            "INSERT INTO categories (name, type, is_default, is_archived, created_at, updated_at) "
            "VALUES (:n, :t, 0, 0, :now, :now)"
        ),
        {"n": name, "t": type_, "now": now},
    )
    return bind.execute(
        sa.text("SELECT id FROM categories WHERE name = :n AND type = :t ORDER BY id DESC LIMIT 1"),
        {"n": name, "t": type_},
    ).scalar_one()


def upgrade() -> None:
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('debt_payment_id', sa.Integer(), nullable=True))
        batch_op.create_unique_constraint(
            batch_op.f('uq_transactions_debt_payment_id'), ['debt_payment_id']
        )
        batch_op.create_foreign_key(
            batch_op.f('fk_transactions_debt_payment_id_debt_payments'),
            'debt_payments',
            ['debt_payment_id'],
            ['id'],
            ondelete='CASCADE',
        )

    bind = op.get_bind()
    payments = bind.execute(
        sa.text(
            "SELECT dp.id, dp.account_id, dp.amount_minor, dp.paid_at, dp.comment, "
            "d.direction, d.currency "
            "FROM debt_payments dp JOIN debts d ON d.id = dp.debt_id "
            "WHERE dp.account_id IS NOT NULL"
        )
    ).all()
    for pid, account_id, amount, paid_at, comment, direction, currency in payments:
        now = _now()
        bind.execute(
            sa.text(
                "INSERT INTO transactions (account_id, category_id, type, amount_minor, "
                "currency, occurred_at, comment, debt_payment_id, created_at, updated_at) "
                "VALUES (:acc, :cat, :type, :amount, :cur, :at, :comment, :pid, :now, :now)"
            ),
            {
                "acc": account_id,
                "cat": _category_id(bind, direction),
                "type": LEDGER_CATEGORY[direction][1],
                "amount": amount,
                "cur": currency,
                "at": paid_at,
                "comment": comment,
                "pid": pid,
                "now": now,
            },
        )


def downgrade() -> None:
    # Старая модель считала баланс по DebtPayment напрямую — связанные
    # операции в ней были бы двойным учётом, поэтому удаляем их.
    op.get_bind().execute(sa.text("DELETE FROM transactions WHERE debt_payment_id IS NOT NULL"))
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f('fk_transactions_debt_payment_id_debt_payments'), type_='foreignkey'
        )
        batch_op.drop_constraint(batch_op.f('uq_transactions_debt_payment_id'), type_='unique')
        batch_op.drop_column('debt_payment_id')
