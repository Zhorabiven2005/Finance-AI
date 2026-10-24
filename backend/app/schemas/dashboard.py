from __future__ import annotations

from app.schemas.accounts import AccountOut
from app.schemas.common import ApiModel
from app.schemas.debts import DebtOut
from app.schemas.money import MoneyOut
from app.schemas.transactions import TransactionOut


class CategorySpendingOut(ApiModel):
    category_id: int
    category_name: str
    icon: str | None
    amount: MoneyOut


class DebtCurrencyTotalOut(ApiModel):
    currency: str
    i_owe: MoneyOut
    owed_to_me: MoneyOut


class DebtsSummaryOut(ApiModel):
    # i_owe_total/owed_to_me_total — только базовая валюта (входят в капитал).
    i_owe_total: MoneyOut
    owed_to_me_total: MoneyOut
    items: list[DebtOut]
    # Остатки по КАЖДОЙ валюте отдельно — разные валюты не суммируются.
    totals_by_currency: list[DebtCurrencyTotalOut] = []
    overdue_count: int = 0


class RecentTransactionOut(TransactionOut):
    account_name: str
    category_name: str
    category_icon: str | None


class DashboardOut(ApiModel):
    net_worth: MoneyOut
    accounts: list[AccountOut]
    debts: DebtsSummaryOut
    recent_transactions: list[RecentTransactionOut]
    top_expenses: list[CategorySpendingOut]
