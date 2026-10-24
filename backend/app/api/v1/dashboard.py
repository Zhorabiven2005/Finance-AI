"""Главный финансовый экран: капитал, счета, долги, последние операции.

Порядок блоков "долги выше счетов, если они есть" — забота фронтенда
(frontend/src/features/dashboard/DashboardPage.tsx): API лишь отдаёт
debts.items, а есть они или нет, решает уже интерфейс.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.accounts import compute_balance, to_out as account_to_out
from app.api.v1.debts import to_out as debt_to_out
from app.db.models import Account, Category, Debt, Transaction
from app.db.models.app_settings import get_base_currency
from app.db.session import get_db
from app.engine.dashboard import net_worth as compute_net_worth
from app.engine.money import Money, get_currency, money_sum
from app.schemas.dashboard import (
    CategorySpendingOut,
    DashboardOut,
    DebtCurrencyTotalOut,
    DebtsSummaryOut,
    RecentTransactionOut,
)
from app.schemas.money import MoneyOut

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

RECENT_TRANSACTIONS_LIMIT = 10
TOP_EXPENSE_CATEGORIES_LIMIT = 5


def _debt_totals_by_currency(open_debts: list) -> list[DebtCurrencyTotalOut]:
    """Остатки открытых долгов по каждой валюте отдельно (без конвертации)."""
    groups: dict[str, dict[str, list[Money]]] = {}
    for d in open_debts:
        cur = d.remaining.currency
        bucket = groups.setdefault(cur, {"i_owe": [], "owed_to_me": []})
        bucket[d.direction].append(Money.of(d.remaining.minor, cur))
    out = []
    for cur in sorted(groups):
        i_owe_sum = money_sum(groups[cur]["i_owe"], cur)
        owed_sum = money_sum(groups[cur]["owed_to_me"], cur)
        out.append(
            DebtCurrencyTotalOut(
                currency=cur,
                i_owe=MoneyOut(minor=i_owe_sum.minor, currency=cur),
                owed_to_me=MoneyOut(minor=owed_sum.minor, currency=cur),
            )
        )
    return out


@router.get("", response_model=DashboardOut)
def get_dashboard(db: Session = Depends(get_db)) -> DashboardOut:
    base_currency = get_currency(get_base_currency(db))

    accounts = list(
        db.scalars(
            select(Account)
            .where(Account.is_active.is_(True))
            .order_by(Account.name)
        )
    )
    accounts_out = [account_to_out(db, a) for a in accounts]
    # Капитал считается только по счетам в базовой валюте: MVP не
    # конвертирует между валютами, а складывать разные валюты нельзя.
    account_balances = [
        compute_balance(db, a) for a in accounts if a.currency == base_currency.code
    ]

    debts = list(db.scalars(select(Debt)))
    debts_out = [debt_to_out(d) for d in debts]
    open_debts = [d for d in debts_out if d.status != "paid"]
    open_debts.sort(key=lambda d: (d.due_date is None, d.due_date, -d.id))

    owed_to_me = [
        Money.of(d.remaining.minor, d.remaining.currency)
        for d in open_debts
        if d.direction == "owed_to_me" and d.remaining.currency == base_currency.code
    ]
    i_owe = [
        Money.of(d.remaining.minor, d.remaining.currency)
        for d in open_debts
        if d.direction == "i_owe" and d.remaining.currency == base_currency.code
    ]

    net_worth = compute_net_worth(account_balances, owed_to_me, i_owe, base_currency)

    recent_txs = list(
        db.scalars(
            select(Transaction)
            .order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
            .limit(RECENT_TRANSACTIONS_LIMIT)
        )
    )
    recent_out = [
        RecentTransactionOut(
            id=tx.id,
            account_id=tx.account_id,
            category_id=tx.category_id,
            type=tx.type,
            amount=MoneyOut(minor=tx.amount_minor, currency=tx.currency),
            occurred_at=tx.occurred_at,
            comment=tx.comment,
            debt_id=tx.debt_payment.debt_id if tx.debt_payment else None,
            debt_name=tx.debt_payment.debt.counterparty_name if tx.debt_payment else None,
            account_name=tx.account.name,
            category_name=tx.category.name,
            category_icon=tx.category.icon,
        )
        for tx in recent_txs
    ]

    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    month_expenses = list(
        db.scalars(
            select(Transaction)
            # Только базовая валюта: суммировать RUB и USD одной категории
            # нельзя (и раньше это роняло весь Dashboard). Так же считаются
            # капитал и аналитика.
            .where(
                Transaction.type == "expense",
                Transaction.occurred_at >= month_start,
                Transaction.currency == base_currency.code,
            )
        )
    )
    by_category: dict[int, list[Money]] = {}
    for tx in month_expenses:
        by_category.setdefault(tx.category_id, []).append(
            Money.of(tx.amount_minor, tx.currency)
        )
    category_lookup = {c.id: c for c in db.scalars(select(Category))}
    top_expenses = []
    for category_id, amounts in by_category.items():
        cur = amounts[0].currency
        total = money_sum(amounts, cur)
        category = category_lookup.get(category_id)
        top_expenses.append(
            CategorySpendingOut(
                category_id=category_id,
                category_name=category.name if category else "—",
                icon=category.icon if category else None,
                amount=MoneyOut(minor=total.minor, currency=total.currency.code),
            )
        )
    top_expenses.sort(key=lambda c: c.amount.minor, reverse=True)
    top_expenses = top_expenses[:TOP_EXPENSE_CATEGORIES_LIMIT]

    return DashboardOut(
        net_worth=MoneyOut(minor=net_worth.minor, currency=net_worth.currency.code),
        accounts=accounts_out,
        debts=DebtsSummaryOut(
            i_owe_total=MoneyOut(
                minor=money_sum(i_owe, base_currency).minor, currency=base_currency.code
            ),
            owed_to_me_total=MoneyOut(
                minor=money_sum(owed_to_me, base_currency).minor,
                currency=base_currency.code,
            ),
            items=open_debts,
            totals_by_currency=_debt_totals_by_currency(open_debts),
            overdue_count=sum(1 for d in open_debts if d.due_state == "overdue"),
        ),
        recent_transactions=recent_out,
        top_expenses=top_expenses,
    )
