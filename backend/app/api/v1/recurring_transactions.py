"""Регулярные операции: шаблон/правило, создающее обычные Transaction по
расписанию — не отдельная запись в журнале (см. docstring модели в
app/db/models/recurring_transaction.py). Баланс счёта отдельно нигде не
трогается: созданная Transaction проходит через уже существующий пересчёт
(app/api/v1/accounts.py), как и любая операция, введённая вручную.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Account,
    Category,
    RecurringTransaction,
    RecurringTransactionRun,
    Transaction,
)
from app.db.session import get_db
from app.engine.recurring import pending_occurrences
from app.schemas.money import MoneyOut
from app.schemas.recurring_transactions import (
    RecurringProcessResultOut,
    RecurringTransactionCreate,
    RecurringTransactionOut,
    RecurringTransactionUpdate,
)

router = APIRouter(prefix="/recurring-transactions", tags=["recurring-transactions"])


def _get_account(db: Session, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Счёт не найден")
    return account


def _get_category(db: Session, category_id: int) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    return category


def _check_category_matches_type(category: Category, type_: str) -> None:
    if category.type != type_:
        raise HTTPException(
            status_code=400,
            detail=f"Категория «{category.name}» относится к типу «{category.type}», а не «{type_}»",
        )


def _check_dates(start_date: date, end_date: date | None) -> None:
    if end_date is not None and end_date < start_date:
        raise HTTPException(
            status_code=400, detail="Дата окончания не может быть раньше даты начала"
        )


def to_out(rule: RecurringTransaction) -> RecurringTransactionOut:
    return RecurringTransactionOut(
        id=rule.id,
        type=rule.type,  # type: ignore[arg-type]
        account_id=rule.account_id,
        account_name=rule.account.name,
        category_id=rule.category_id,
        category_name=rule.category.name,
        category_icon=rule.category.icon,
        amount=MoneyOut(minor=rule.amount_minor, currency=rule.currency),
        comment=rule.comment,
        start_date=rule.start_date,
        end_date=rule.end_date,
        frequency=rule.frequency,  # type: ignore[arg-type]
        next_run_date=rule.next_run_date,
        is_active=rule.is_active,
    )


def get_rule_or_404(db: Session, rule_id: int) -> RecurringTransaction:
    rule = db.get(RecurringTransaction, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Регулярная операция не найдена")
    return rule


@router.post("", response_model=RecurringTransactionOut, status_code=201)
def create_recurring_transaction(
    payload: RecurringTransactionCreate, db: Session = Depends(get_db)
) -> RecurringTransactionOut:
    account = _get_account(db, payload.account_id)
    category = _get_category(db, payload.category_id)
    _check_category_matches_type(category, payload.type)
    _check_dates(payload.start_date, payload.end_date)

    next_run_date = payload.next_run_date or payload.start_date
    if next_run_date < payload.start_date:
        raise HTTPException(
            status_code=400,
            detail="Дата следующей операции не может быть раньше даты начала",
        )

    rule = RecurringTransaction(
        type=payload.type,
        account_id=account.id,
        category_id=category.id,
        amount_minor=payload.amount_minor,
        # Валюта — от счёта, как и у обычной Transaction (см.
        # app/api/v1/transactions.py): пользователь её не выбирает отдельно,
        # это исключает рассинхронизацию счёта и операции по валюте.
        currency=account.currency,
        comment=payload.comment,
        start_date=payload.start_date,
        end_date=payload.end_date,
        frequency=payload.frequency,
        next_run_date=next_run_date,
        is_active=True,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return to_out(rule)


@router.get("", response_model=list[RecurringTransactionOut])
def list_recurring_transactions(
    is_active: bool | None = None,
    db: Session = Depends(get_db),
) -> list[RecurringTransactionOut]:
    stmt = select(RecurringTransaction).order_by(RecurringTransaction.next_run_date)
    if is_active is not None:
        stmt = stmt.where(RecurringTransaction.is_active.is_(is_active))
    return [to_out(r) for r in db.scalars(stmt).all()]


@router.get("/{rule_id}", response_model=RecurringTransactionOut)
def get_recurring_transaction(
    rule_id: int, db: Session = Depends(get_db)
) -> RecurringTransactionOut:
    return to_out(get_rule_or_404(db, rule_id))


@router.patch("/{rule_id}", response_model=RecurringTransactionOut)
def update_recurring_transaction(
    rule_id: int, payload: RecurringTransactionUpdate, db: Session = Depends(get_db)
) -> RecurringTransactionOut:
    rule = get_rule_or_404(db, rule_id)
    data = payload.model_dump(exclude_unset=True)

    if "account_id" in data:
        account = _get_account(db, data["account_id"])
        rule.account_id = account.id
        rule.currency = account.currency
    if "category_id" in data:
        category = _get_category(db, data["category_id"])
        _check_category_matches_type(category, rule.type)
        rule.category_id = category.id
    if "amount_minor" in data:
        rule.amount_minor = data["amount_minor"]
    if "comment" in data:
        rule.comment = data["comment"]
    if "end_date" in data:
        _check_dates(rule.start_date, data["end_date"])
        rule.end_date = data["end_date"]
    if "is_active" in data:
        rule.is_active = data["is_active"]

    db.commit()
    db.refresh(rule)
    return to_out(rule)


@router.delete("/{rule_id}", status_code=204)
def delete_recurring_transaction(rule_id: int, db: Session = Depends(get_db)) -> None:
    # Удаляется только правило (и его RecurringTransactionRun каскадом) —
    # уже сгенерированные Transaction остаются: это обычные операции,
    # независимые от шаблона, который их создал.
    rule = get_rule_or_404(db, rule_id)
    db.delete(rule)
    db.commit()


def process_recurring_transactions(db: Session, current_date: date) -> RecurringProcessResultOut:
    """Создаёт Transaction для всех пропущенных дат активных правил.

    Идемпотентно: next_run_date продвигается только после успешной
    обработки и коммитится атомарно вместе с созданными операциями, поэтому
    повторный вызов с той же current_date видит уже сдвинутый next_run_date
    и не находит новых дат к обработке. RecurringTransactionRun с уникальным
    (rule_id, run_date) — независимая от этого вторая линия защиты на
    уровне БД, а не только полагание на корректность next_run_date.
    """
    created_count = 0
    deactivated_count = 0

    rules = list(
        db.scalars(
            select(RecurringTransaction).where(RecurringTransaction.is_active.is_(True))
        )
    )
    for rule in rules:
        occurrences, new_next_run_date, still_active = pending_occurrences(
            rule.next_run_date,
            current_date,
            rule.frequency,  # type: ignore[arg-type]
            rule.end_date,
        )
        for occurrence_date in occurrences:
            already_run = db.scalar(
                select(RecurringTransactionRun.id).where(
                    RecurringTransactionRun.recurring_transaction_id == rule.id,
                    RecurringTransactionRun.run_date == occurrence_date,
                )
            )
            if already_run is not None:
                continue

            tx = Transaction(
                account_id=rule.account_id,
                category_id=rule.category_id,
                type=rule.type,
                amount_minor=rule.amount_minor,
                currency=rule.currency,
                occurred_at=datetime.combine(occurrence_date, time(12, 0), tzinfo=timezone.utc),
                comment=rule.comment,
            )
            db.add(tx)
            db.flush()  # нужен tx.id перед вставкой RecurringTransactionRun
            db.add(
                RecurringTransactionRun(
                    recurring_transaction_id=rule.id,
                    run_date=occurrence_date,
                    transaction_id=tx.id,
                )
            )
            created_count += 1

        rule.next_run_date = new_next_run_date
        if not still_active:
            deactivated_count += 1
        rule.is_active = still_active

    db.commit()
    return RecurringProcessResultOut(
        created_transactions=created_count, deactivated_rules=deactivated_count
    )


@router.post("/process", response_model=RecurringProcessResultOut)
def process_recurring(
    as_of: date | None = None, db: Session = Depends(get_db)
) -> RecurringProcessResultOut:
    current_date = as_of or datetime.now(timezone.utc).date()
    return process_recurring_transactions(db, current_date)
