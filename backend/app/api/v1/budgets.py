"""Бюджеты: лимит расходов по категории на календарный месяц.

spent считается заново при каждом запросе из Transaction (см.
app/engine/budgets.py:month_bounds), а не кешируется — поэтому не может
разойтись с реальными расходами после редактирования/удаления операции,
тем же принципом, что уже применяется для баланса счёта и остатка долга.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Budget, Category, Transaction
from app.db.session import get_db
from app.engine.budgets import calculate_budget_usage, month_bounds
from app.engine.money import Money, get_currency, money_sum
from app.schemas.budgets import BudgetCreate, BudgetOut, BudgetUpdate
from app.schemas.money import MoneyOut

router = APIRouter(prefix="/budgets", tags=["budgets"])

DUPLICATE_DETAIL = "Бюджет для этой категории на этот месяц и валюту уже существует"


def _get_category(db: Session, category_id: int) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    return category


def _check_expense_category(category: Category) -> None:
    if category.type != "expense":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Бюджет можно установить только для расходной категории, "
                f"а «{category.name}» относится к доходам"
            ),
        )


def _check_duplicate(
    db: Session,
    category_id: int,
    year: int,
    month: int,
    currency: str,
    exclude_id: int | None = None,
) -> None:
    stmt = select(Budget.id).where(
        Budget.category_id == category_id,
        Budget.year == year,
        Budget.month == month,
        Budget.currency == currency,
    )
    if exclude_id is not None:
        stmt = stmt.where(Budget.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise HTTPException(status_code=400, detail=DUPLICATE_DETAIL)


def compute_spent(db: Session, budget: Budget) -> Money:
    cur = get_currency(budget.currency)
    start, end = month_bounds(budget.year, budget.month)
    rows = db.scalars(
        select(Transaction).where(
            Transaction.category_id == budget.category_id,
            Transaction.type == "expense",
            Transaction.currency == budget.currency,
            Transaction.occurred_at >= start,
            Transaction.occurred_at <= end,
        )
    )
    return money_sum((Money.of(t.amount_minor, cur) for t in rows), cur)


def to_out(db: Session, budget: Budget) -> BudgetOut:
    cur = get_currency(budget.currency)
    amount = Money.of(budget.amount_minor, cur)
    spent = compute_spent(db, budget)
    remaining, usage_percent, status = calculate_budget_usage(spent, amount)
    category = budget.category
    return BudgetOut(
        id=budget.id,
        category_id=budget.category_id,
        category_name=category.name,
        category_icon=category.icon,
        amount=MoneyOut(minor=amount.minor, currency=cur.code),
        year=budget.year,
        month=budget.month,
        spent=MoneyOut(minor=spent.minor, currency=cur.code),
        remaining=MoneyOut(minor=remaining.minor, currency=cur.code),
        usage_percent=float(usage_percent),
        status=status.value,  # type: ignore[arg-type]
    )


def get_budget_or_404(db: Session, budget_id: int) -> Budget:
    budget = db.get(Budget, budget_id)
    if budget is None:
        raise HTTPException(status_code=404, detail="Бюджет не найден")
    return budget


@router.post("", response_model=BudgetOut, status_code=201)
def create_budget(payload: BudgetCreate, db: Session = Depends(get_db)) -> BudgetOut:
    category = _get_category(db, payload.category_id)
    _check_expense_category(category)
    currency = get_currency(payload.currency)
    _check_duplicate(db, category.id, payload.year, payload.month, currency.code)

    budget = Budget(
        category_id=category.id,
        amount_minor=payload.amount_minor,
        currency=currency.code,
        year=payload.year,
        month=payload.month,
    )
    db.add(budget)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail=DUPLICATE_DETAIL) from None
    db.refresh(budget)
    return to_out(db, budget)


@router.get("", response_model=list[BudgetOut])
def list_budgets(
    year: int | None = None,
    month: int | None = None,
    db: Session = Depends(get_db),
) -> list[BudgetOut]:
    stmt = select(Budget)
    if year is not None:
        stmt = stmt.where(Budget.year == year)
    if month is not None:
        stmt = stmt.where(Budget.month == month)
    budgets = list(db.scalars(stmt).all())
    out = [to_out(db, b) for b in budgets]
    out.sort(key=lambda b: (-b.year, -b.month, b.category_name))
    return out


@router.get("/{budget_id}", response_model=BudgetOut)
def get_budget(budget_id: int, db: Session = Depends(get_db)) -> BudgetOut:
    return to_out(db, get_budget_or_404(db, budget_id))


@router.patch("/{budget_id}", response_model=BudgetOut)
def update_budget(
    budget_id: int, payload: BudgetUpdate, db: Session = Depends(get_db)
) -> BudgetOut:
    budget = get_budget_or_404(db, budget_id)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(budget, field, value)
    db.commit()
    db.refresh(budget)
    return to_out(db, budget)


@router.delete("/{budget_id}", status_code=204)
def delete_budget(budget_id: int, db: Session = Depends(get_db)) -> None:
    budget = get_budget_or_404(db, budget_id)
    db.delete(budget)
    db.commit()
