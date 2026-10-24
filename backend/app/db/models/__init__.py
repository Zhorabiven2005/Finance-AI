"""ORM-модели.

Все модели импортируются здесь, чтобы Alembic видел полную метадату
при автогенерации миграций.
"""

from app.db.models.account import Account
from app.db.models.app_settings import AppSettings
from app.db.models.budget import Budget
from app.db.models.category import Category
from app.db.models.debt import Debt, DebtPayment
from app.db.models.goal import Goal, GoalEntry
from app.db.models.notification import Notification
from app.db.models.recurring_transaction import RecurringTransaction, RecurringTransactionRun
from app.db.models.transaction import Transaction
from app.db.models.transfer import Transfer

__all__ = [
    "Account",
    "AppSettings",
    "Budget",
    "Category",
    "Debt",
    "DebtPayment",
    "Goal",
    "GoalEntry",
    "Notification",
    "RecurringTransaction",
    "RecurringTransactionRun",
    "Transaction",
    "Transfer",
]
