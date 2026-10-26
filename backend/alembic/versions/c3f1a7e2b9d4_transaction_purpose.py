"""transaction purpose (manual classification)

Stage 3F: пользователь вручную отмечает назначение операции — перевод между
своими счетами, перевод на свой внешний продукт или погашение долга. Для
этого в transactions добавляются три nullable-колонки:

  * purpose — NULL (обычный доход или расход) или одно из значений
    TRANSACTION_PURPOSES (app/db/models/transaction.py);
  * purpose_account_id — второй свой счёт для перевода между своими счетами;
  * purpose_debt_id — долг, который погашает операция (необязательно).

Миграция минимальная и обратно совместимая: только ALTER TABLE ADD COLUMN
без пересоздания таблицы, существующие строки не переписываются — у всех
старых операций purpose = NULL, то есть они остаются обычными доходами и
расходами. Внешних ключей нет намеренно (как у notifications.entity_id):
удаление счёта или долга не должно затрагивать саму операцию; связи
проверяет приложение при записи.

Revision ID: c3f1a7e2b9d4
Revises: 36106d4a5974
Create Date: 2026-10-26 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3f1a7e2b9d4'
down_revision: Union[str, None] = '36106d4a5974'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('transactions', sa.Column('purpose', sa.String(length=30), nullable=True))
    op.add_column('transactions', sa.Column('purpose_account_id', sa.Integer(), nullable=True))
    op.add_column('transactions', sa.Column('purpose_debt_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    # Откат удаляет только ручную классификацию; суммы, даты, счета и
    # комментарии операций не затрагиваются.
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_column('purpose_debt_id')
        batch_op.drop_column('purpose_account_id')
        batch_op.drop_column('purpose')
