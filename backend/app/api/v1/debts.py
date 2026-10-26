"""Долги: кто кому должен, статус и погашение.

Остаток и статус долга нигде не хранятся — они всегда выводятся заново из
principal и истории платежей (см. app/engine/debts.py), поэтому погашение
не может рассинхронизировать долг со статусом.

Платёж, привязанный к счёту, — движение денег, и оно живёт в журнале как ОДНА
связанная Transaction (Transaction.debt_payment_id). Баланс счёта, журнал
операций, Dashboard и аналитика читают только Transaction, поэтому платёж
нигде не учитывается дважды. Платёж без счёта операции не создаёт.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Account, Category, Debt, DebtPayment, Transaction
from app.db.session import get_db
from app import clock
from app.engine.debts import debt_due_state, debt_paid_percent, debt_remaining, debt_status
from app.engine.money import Money, get_currency
from app.schemas.debts import (
    DebtCreate,
    DebtOut,
    DebtPaymentCreate,
    DebtPaymentOut,
    DebtPaymentUpdate,
    DebtUpdate,
)
from app.schemas.money import MoneyOut

router = APIRouter(prefix="/debts", tags=["debts"])

# direction -> (имя базовой категории, тип операции). Я погашаю долг — деньги
# уходят со счёта (расход); мне возвращают долг — приходят на счёт (доход).
DEBT_LEDGER_CATEGORY = {
    "i_owe": ("Погашение долга", "expense"),
    "owed_to_me": ("Возврат долга", "income"),
}


def _payments_money(debt: Debt) -> list[Money]:
    cur = get_currency(debt.currency)
    return [Money.of(p.amount_minor, cur) for p in debt.payments]


def to_out(debt: Debt, today: date | None = None) -> DebtOut:
    today = today or clock.today()
    cur = get_currency(debt.currency)
    principal = Money.of(debt.principal_minor, cur)
    remaining = debt_remaining(principal, _payments_money(debt))
    paid = principal - remaining
    status = debt_status(principal, remaining)
    return DebtOut(
        id=debt.id,
        counterparty_name=debt.counterparty_name,
        direction=debt.direction,  # type: ignore[arg-type]
        principal=MoneyOut(minor=principal.minor, currency=principal.currency.code),
        paid=MoneyOut(minor=paid.minor, currency=paid.currency.code),
        remaining=MoneyOut(minor=remaining.minor, currency=remaining.currency.code),
        status=status.value,  # type: ignore[arg-type]
        due_date=debt.due_date,
        comment=debt.comment,
        paid_percent=float(debt_paid_percent(principal, remaining)),
        due_state=debt_due_state(debt.due_date, remaining.minor, today).value,  # type: ignore[arg-type]
        days_until_due=(debt.due_date - today).days if debt.due_date else None,
        created_at=debt.created_at,
    )


def payment_to_out(payment: DebtPayment) -> DebtPaymentOut:
    return DebtPaymentOut(
        id=payment.id,
        debt_id=payment.debt_id,
        account_id=payment.account_id,
        transaction_id=payment.transaction.id if payment.transaction else None,
        amount=MoneyOut(minor=payment.amount_minor, currency=payment.debt.currency),
        paid_at=payment.paid_at,
        comment=payment.comment,
    )


def get_debt_or_404(db: Session, debt_id: int) -> Debt:
    debt = db.get(Debt, debt_id)
    if debt is None:
        raise HTTPException(status_code=404, detail="Долг не найден")
    return debt


@router.post("", response_model=DebtOut, status_code=201)
def create_debt(payload: DebtCreate, db: Session = Depends(get_db)) -> DebtOut:
    currency = get_currency(payload.currency)
    debt = Debt(
        counterparty_name=payload.counterparty_name.strip(),
        direction=payload.direction,
        principal_minor=payload.principal_minor,
        currency=currency.code,
        due_date=payload.due_date,
        comment=payload.comment,
    )
    db.add(debt)
    db.commit()
    db.refresh(debt)
    return to_out(debt)


@router.get("", response_model=list[DebtOut])
def list_debts(
    status: str | None = None,
    direction: str | None = None,
    db: Session = Depends(get_db),
) -> list[DebtOut]:
    stmt = select(Debt).order_by(Debt.due_date.is_(None), Debt.due_date, Debt.id.desc())
    if direction is not None:
        stmt = stmt.where(Debt.direction == direction)
    debts = [to_out(d) for d in db.scalars(stmt).all()]
    if status is not None:
        debts = [d for d in debts if d.status == status]
    return debts


@router.get("/{debt_id}", response_model=DebtOut)
def get_debt(debt_id: int, db: Session = Depends(get_db)) -> DebtOut:
    return to_out(get_debt_or_404(db, debt_id))


@router.patch("/{debt_id}", response_model=DebtOut)
def update_debt(debt_id: int, payload: DebtUpdate, db: Session = Depends(get_db)) -> DebtOut:
    debt = get_debt_or_404(db, debt_id)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(debt, field, value)
    db.commit()
    db.refresh(debt)
    return to_out(debt)


@router.delete("/{debt_id}", status_code=204)
def delete_debt(debt_id: int, db: Session = Depends(get_db)) -> None:
    # Платежи и их связанные операции удаляются каскадом (ORM + ON DELETE).
    debt = get_debt_or_404(db, debt_id)
    # Операции, вручную отмеченные погашением этого долга, остаются, но
    # ссылка на удалённый долг снимается (назначение «погашение» сохраняется).
    db.execute(update(Transaction).where(Transaction.purpose_debt_id == debt.id).values(purpose_debt_id=None))
    db.delete(debt)
    db.commit()


def _ledger_category(db: Session, direction: str) -> Category:
    name, type_ = DEBT_LEDGER_CATEGORY[direction]
    category = db.scalar(
        select(Category)
        .where(Category.name == name, Category.type == type_)
        .order_by(Category.is_default.desc(), Category.id)
        .limit(1)
    )
    if category is None:
        category = Category(name=name, type=type_, is_default=False, is_archived=False)
        db.add(category)
        db.flush()
    return category


def _resolve_account(db: Session, account_id: int | None, debt: Debt) -> Account | None:
    if account_id is None:
        return None
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Счёт не найден")
    if account.currency != debt.currency:
        raise HTTPException(
            status_code=400,
            detail="Валюта счёта должна совпадать с валютой долга",
        )
    return account


def _sync_ledger_transaction(
    db: Session, payment: DebtPayment, debt: Debt, account: Account | None
) -> None:
    """Приводит связанную операцию в соответствие с платежом: нет счёта —
    нет операции, есть счёт — ровно одна операция с актуальными полями."""
    if account is None:
        payment.account_id = None
        payment.transaction = None
        return
    category = _ledger_category(db, debt.direction)
    tx = payment.transaction or Transaction()
    tx.account_id = account.id
    tx.category_id = category.id
    tx.type = DEBT_LEDGER_CATEGORY[debt.direction][1]
    tx.amount_minor = payment.amount_minor
    tx.currency = account.currency
    tx.occurred_at = payment.paid_at
    tx.comment = payment.comment
    payment.account_id = account.id
    payment.transaction = tx


def _check_not_overpaying(debt: Debt, amount_minor: int, excluded: DebtPayment | None) -> None:
    cur = get_currency(debt.currency)
    principal = Money.of(debt.principal_minor, cur)
    others = [Money.of(p.amount_minor, cur) for p in debt.payments if p is not excluded]
    remaining = debt_remaining(principal, others)
    amount = Money.of(amount_minor, cur)
    if amount.minor > remaining.minor:
        raise HTTPException(
            status_code=400,
            detail=f"Сумма погашения ({amount.format()}) больше остатка долга ({remaining.format()})",
        )


def _get_payment_or_404(db: Session, debt_id: int, payment_id: int) -> DebtPayment:
    payment = db.get(DebtPayment, payment_id)
    if payment is None or payment.debt_id != debt_id:
        raise HTTPException(status_code=404, detail="Платёж не найден")
    return payment


@router.post("/{debt_id}/payments", response_model=DebtPaymentOut, status_code=201)
def add_debt_payment(
    debt_id: int, payload: DebtPaymentCreate, db: Session = Depends(get_db)
) -> DebtPaymentOut:
    debt = get_debt_or_404(db, debt_id)
    _check_not_overpaying(debt, payload.amount_minor, None)
    account = _resolve_account(db, payload.account_id, debt)

    payment = DebtPayment(
        debt_id=debt.id,
        amount_minor=payload.amount_minor,
        paid_at=payload.paid_at,
        comment=payload.comment,
    )
    db.add(payment)
    _sync_ledger_transaction(db, payment, debt, account)
    db.commit()
    db.refresh(payment)
    return payment_to_out(payment)


@router.get("/{debt_id}/payments", response_model=list[DebtPaymentOut])
def list_debt_payments(debt_id: int, db: Session = Depends(get_db)) -> list[DebtPaymentOut]:
    debt = get_debt_or_404(db, debt_id)
    return [
        payment_to_out(p)
        for p in sorted(debt.payments, key=lambda p: p.paid_at, reverse=True)
    ]


@router.patch("/{debt_id}/payments/{payment_id}", response_model=DebtPaymentOut)
def update_debt_payment(
    debt_id: int,
    payment_id: int,
    payload: DebtPaymentUpdate,
    db: Session = Depends(get_db),
) -> DebtPaymentOut:
    payment = _get_payment_or_404(db, debt_id, payment_id)
    debt = payment.debt
    fields = payload.model_fields_set

    if "amount_minor" in fields and payload.amount_minor is not None:
        _check_not_overpaying(debt, payload.amount_minor, payment)
        payment.amount_minor = payload.amount_minor
    if "paid_at" in fields and payload.paid_at is not None:
        payment.paid_at = payload.paid_at
    if "comment" in fields:
        payment.comment = payload.comment

    account_id = payload.account_id if "account_id" in fields else payment.account_id
    account = _resolve_account(db, account_id, debt)
    _sync_ledger_transaction(db, payment, debt, account)
    db.commit()
    db.refresh(payment)
    return payment_to_out(payment)


@router.delete("/{debt_id}/payments/{payment_id}", status_code=204)
def delete_debt_payment(
    debt_id: int, payment_id: int, db: Session = Depends(get_db)
) -> None:
    payment = _get_payment_or_404(db, debt_id, payment_id)
    # Удаление через коллекцию (delete-orphan), а не db.delete: так уже
    # загруженный в сессию debt.payments не остаётся устаревшим. Связанная
    # операция удаляется каскадом вместе с платежом.
    payment.debt.payments.remove(payment)
    db.commit()
