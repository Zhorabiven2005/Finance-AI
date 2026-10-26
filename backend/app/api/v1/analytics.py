"""Финансовая аналитика: сводка, сравнение с предыдущим периодом,
временной ряд, разбивка по категориям, крупнейшие расходы.

Всё считается за ОДИН период и отдаётся ОДНИМ ответом (см.
app/schemas/analytics.py) — так карточки и график физически не могут
показывать разные периоды: это не соглашение между эндпоинтами, а
единственный способ, которым тут вообще можно получить данные.

Расчёты идут в Python поверх выборки, уже ограниченной периодом и валютой
(а не всей историей) — SQLite не умеет группировать по ISO-неделям и
календарным месяцам на уровне SQL, а объём данных личного бюджета за
период (даже год) не требует агрегации в самой БД. Если это когда-нибудь
перестанет быть верным — см. заметку в финальном отчёте Stage 2A.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Category, Transaction
from app.db.models.app_settings import get_base_currency
from app.db.session import get_db
from app.engine.analytics import (
    bucket_key,
    choose_granularity,
    generate_buckets,
    percent_change,
    previous_period,
    share_percent,
)
from app.engine.flows import is_transfer
from app.engine.money import Currency, Money, get_currency, money_sum
from app.schemas.analytics import (
    AnalyticsOut,
    AnalyticsSummaryOut,
    CategoryBreakdownItemOut,
    PeriodComparisonOut,
    TimeseriesPointOut,
    TopExpenseItemOut,
)
from app.schemas.money import MoneyOut

router = APIRouter(prefix="/analytics", tags=["analytics"])

TOP_EXPENSES_LIMIT = 5


def _to_percent(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _period_transactions(
    db: Session, currency: str, date_from: datetime, date_to: datetime
) -> list[Transaction]:
    """Операции периода, кроме отмеченных пользователем переводов (Stage 3F,
    app/engine/flows.py): переводы — не доходы и не расходы. Погашения долгов
    остаются в расходах, как и раньше: аналитика показывает все расходы."""
    rows = db.scalars(
        select(Transaction).where(
            Transaction.currency == currency,
            Transaction.occurred_at >= date_from,
            Transaction.occurred_at <= date_to,
        )
    )
    return [t for t in rows if not is_transfer(t)]


def _totals(transactions: list[Transaction], currency: Currency) -> tuple[Money, Money]:
    income = money_sum(
        (Money.of(t.amount_minor, currency) for t in transactions if t.type == "income"),
        currency,
    )
    expense = money_sum(
        (Money.of(t.amount_minor, currency) for t in transactions if t.type == "expense"),
        currency,
    )
    return income, expense


@router.get("", response_model=AnalyticsOut)
def get_analytics(
    date_from: datetime,
    date_to: datetime,
    db: Session = Depends(get_db),
) -> AnalyticsOut:
    if date_from > date_to:
        raise HTTPException(
            status_code=400, detail="Начало периода не может быть позже конца"
        )

    currency = get_currency(get_base_currency(db))
    granularity = choose_granularity(date_from, date_to)

    transactions = _period_transactions(db, currency.code, date_from, date_to)
    income, expense = _totals(transactions, currency)
    balance = income - expense

    prev_from, prev_to = previous_period(date_from, date_to)
    prev_transactions = _period_transactions(db, currency.code, prev_from, prev_to)
    prev_income, prev_expense = _totals(prev_transactions, currency)

    comparison = PeriodComparisonOut(
        has_previous_data=len(prev_transactions) > 0,
        previous_income=MoneyOut(minor=prev_income.minor, currency=currency.code),
        previous_expense=MoneyOut(minor=prev_expense.minor, currency=currency.code),
        income_change_percent=_to_percent(percent_change(income, prev_income)),
        expense_change_percent=_to_percent(percent_change(expense, prev_expense)),
    )

    buckets = generate_buckets(date_from, date_to, granularity)
    income_by_bucket = {b: Money.zero(currency) for b in buckets}
    expense_by_bucket = {b: Money.zero(currency) for b in buckets}
    for t in transactions:
        b = bucket_key(t.occurred_at, granularity)
        amount = Money.of(t.amount_minor, currency)
        if t.type == "income":
            income_by_bucket[b] = income_by_bucket[b] + amount
        else:
            expense_by_bucket[b] = expense_by_bucket[b] + amount
    timeseries = [
        TimeseriesPointOut(
            period_start=b,
            income=MoneyOut(minor=income_by_bucket[b].minor, currency=currency.code),
            expense=MoneyOut(minor=expense_by_bucket[b].minor, currency=currency.code),
        )
        for b in buckets
    ]

    category_totals: dict[int, Money] = {}
    for t in transactions:
        if t.type != "expense":
            continue
        amount = Money.of(t.amount_minor, currency)
        category_totals[t.category_id] = category_totals.get(
            t.category_id, Money.zero(currency)
        ) + amount
    category_lookup = {c.id: c for c in db.scalars(select(Category))}
    category_breakdown = [
        CategoryBreakdownItemOut(
            category_id=cid,
            category_name=category_lookup[cid].name if cid in category_lookup else "—",
            category_icon=category_lookup[cid].icon if cid in category_lookup else None,
            amount=MoneyOut(minor=amount.minor, currency=currency.code),
            percent=_to_percent(share_percent(amount, expense)) or 0.0,
        )
        for cid, amount in category_totals.items()
    ]
    category_breakdown.sort(key=lambda item: item.amount.minor, reverse=True)

    top_expense_txs = sorted(
        (t for t in transactions if t.type == "expense"),
        key=lambda t: t.amount_minor,
        reverse=True,
    )[:TOP_EXPENSES_LIMIT]
    top_expenses = [
        TopExpenseItemOut(
            transaction_id=t.id,
            amount=MoneyOut(minor=t.amount_minor, currency=t.currency),
            category_name=t.category.name,
            category_icon=t.category.icon,
            account_name=t.account.name,
            occurred_at=t.occurred_at,
            comment=t.comment,
        )
        for t in top_expense_txs
    ]

    return AnalyticsOut(
        date_from=date_from,
        date_to=date_to,
        currency=currency.code,
        granularity=granularity,
        summary=AnalyticsSummaryOut(
            income=MoneyOut(minor=income.minor, currency=currency.code),
            expense=MoneyOut(minor=expense.minor, currency=currency.code),
            balance=MoneyOut(minor=balance.minor, currency=currency.code),
            transaction_count=len(transactions),
        ),
        comparison=comparison,
        timeseries=timeseries,
        category_breakdown=category_breakdown,
        top_expenses=top_expenses,
    )
