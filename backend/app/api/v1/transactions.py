"""Доходы и расходы.

Баланс счёта нигде здесь явно не пересчитывается и не инкрементируется —
он всегда выводится заново из текущего набора операций (см.
app/api/v1/accounts.py). Поэтому создание, изменение и удаление операции
автоматически дают корректный баланс без отдельного шага синхронизации.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Account, Category, Debt, Transaction
from app.db.session import get_db
from app.engine.flows import PURPOSE_DEBT_REPAYMENT, PURPOSE_OWN_TRANSFER, allowed_purposes
from app.schemas.money import MoneyOut
from app.schemas.transactions import (
    TransactionCreate,
    TransactionOut,
    TransactionPurposeUpdate,
    TransactionUpdate,
)

router = APIRouter(prefix="/transactions", tags=["transactions"])

SortBy = Literal["occurred_at", "amount_minor"]
SortDir = Literal["asc", "desc"]
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def to_out(tx: Transaction) -> TransactionOut:
    return TransactionOut(
        id=tx.id,
        account_id=tx.account_id,
        category_id=tx.category_id,
        type=tx.type,
        amount=MoneyOut(minor=tx.amount_minor, currency=tx.currency),
        occurred_at=tx.occurred_at,
        comment=tx.comment,
        debt_id=tx.debt_payment.debt_id if tx.debt_payment else None,
        debt_name=tx.debt_payment.debt.counterparty_name if tx.debt_payment else None,
        purpose=tx.purpose,  # type: ignore[arg-type]
        purpose_account_id=tx.purpose_account_id,
        purpose_debt_id=tx.purpose_debt_id,
    )


def _reject_if_debt_payment(tx: Transaction) -> None:
    # Операция-погашение принадлежит платежу по долгу: меняя или удаляя её
    # отсюда, можно рассинхронизировать долг и счёт.
    if tx.debt_payment_id is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Эта операция создана погашением долга — измените или удалите "
                "платёж в разделе «Долги»"
            ),
        )


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


PURPOSE_HINT = "Сначала верните операции обычный тип (назначение «Обычная операция»), затем измените её."


def _check_purpose(
    db: Session,
    *,
    tx_type: str,
    account_id: int,
    currency: str,
    purpose: str | None,
    purpose_account_id: int | None,
    purpose_debt_id: int | None,
) -> None:
    """Согласованность назначения с операцией. Ошибка — 422 с понятным
    текстом: какое поле заполнить или почему выбор невозможен."""
    if purpose is None:
        if purpose_account_id is not None or purpose_debt_id is not None:
            raise HTTPException(status_code=422, detail="Счёт и долг указываются только вместе с назначением")
        return
    if purpose not in allowed_purposes(tx_type):
        raise HTTPException(status_code=422, detail="Погашением долга может быть только расход")
    if purpose == PURPOSE_OWN_TRANSFER:
        if purpose_account_id is None:
            raise HTTPException(status_code=422, detail="Укажите второй свой счёт, участвующий в переводе")
        other = db.get(Account, purpose_account_id)
        if other is None:
            raise HTTPException(status_code=422, detail="Второй счёт не найден")
        if other.id == account_id:
            raise HTTPException(status_code=422, detail="Второй счёт должен отличаться от счёта операции")
        if other.currency != currency:
            raise HTTPException(status_code=422, detail="Перевод между своими счетами возможен только в одной валюте")
    elif purpose_account_id is not None:
        raise HTTPException(status_code=422, detail="Второй счёт указывается только для перевода между своими счетами")
    if purpose == PURPOSE_DEBT_REPAYMENT:
        if purpose_debt_id is not None:
            debt = db.get(Debt, purpose_debt_id)
            if debt is None:
                raise HTTPException(status_code=422, detail="Долг не найден")
            if debt.direction != "i_owe":
                raise HTTPException(status_code=422, detail="Погашать можно только долг, где должны вы")
            if debt.currency != currency:
                raise HTTPException(status_code=422, detail="Валюта долга не совпадает с валютой операции")
    elif purpose_debt_id is not None:
        raise HTTPException(status_code=422, detail="Долг указывается только для погашения долга")


def get_transaction_or_404(db: Session, transaction_id: int) -> Transaction:
    tx = db.get(Transaction, transaction_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="Операция не найдена")
    return tx


@router.post("", response_model=TransactionOut, status_code=201)
def create_transaction(
    payload: TransactionCreate, db: Session = Depends(get_db)
) -> TransactionOut:
    account = _get_account(db, payload.account_id)
    category = _get_category(db, payload.category_id)
    _check_category_matches_type(category, payload.type)

    tx = Transaction(
        account_id=account.id,
        category_id=category.id,
        type=payload.type,
        amount_minor=payload.amount_minor,
        currency=account.currency,
        occurred_at=payload.occurred_at,
        comment=payload.comment,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return to_out(tx)


@router.get("", response_model=list[TransactionOut])
def list_transactions(
    response: Response,
    account_id: int | None = None,
    category_id: int | None = None,
    type: Literal["income", "expense"] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    amount_min: int | None = None,
    amount_max: int | None = None,
    search: str | None = None,
    sort_by: SortBy = "occurred_at",
    sort_dir: SortDir = "desc",
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[TransactionOut]:
    """Список операций с фильтрами, поиском, сортировкой и пагинацией.

    Тело ответа осталось `list[TransactionOut]` ради обратной совместимости
    с Stage 1 (frontend и тесты ожидают голый массив). Общее количество
    строк, подходящих под фильтр (без limit/offset), отдаётся в заголовке
    X-Total-Count — так пагинация не требует менять форму ответа.
    """
    stmt = select(Transaction)
    count_stmt = select(func.count(Transaction.id))

    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)
        count_stmt = count_stmt.where(Transaction.account_id == account_id)
    if category_id is not None:
        stmt = stmt.where(Transaction.category_id == category_id)
        count_stmt = count_stmt.where(Transaction.category_id == category_id)
    if type is not None:
        stmt = stmt.where(Transaction.type == type)
        count_stmt = count_stmt.where(Transaction.type == type)
    if date_from is not None:
        stmt = stmt.where(Transaction.occurred_at >= date_from)
        count_stmt = count_stmt.where(Transaction.occurred_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Transaction.occurred_at <= date_to)
        count_stmt = count_stmt.where(Transaction.occurred_at <= date_to)
    if amount_min is not None:
        stmt = stmt.where(Transaction.amount_minor >= amount_min)
        count_stmt = count_stmt.where(Transaction.amount_minor >= amount_min)
    if amount_max is not None:
        stmt = stmt.where(Transaction.amount_minor <= amount_max)
        count_stmt = count_stmt.where(Transaction.amount_minor <= amount_max)

    term = (search or "").strip()
    if term:
        # casefold_unicode — функция, зарегистрированная на соединении SQLite
        # (см. app/db/session.py): обычный LIKE в SQLite регистронезависим
        # только для ASCII и не находит "Кафе" по запросу "кафе".
        pattern = f"%{term.casefold()}%"
        casefold = func.casefold_unicode
        search_condition = or_(
            casefold(Transaction.comment).like(pattern),
            casefold(Category.name).like(pattern),
            casefold(Account.name).like(pattern),
        )
        stmt = stmt.join(Category, Transaction.category_id == Category.id).join(
            Account, Transaction.account_id == Account.id
        ).where(search_condition)
        count_stmt = count_stmt.join(
            Category, Transaction.category_id == Category.id
        ).join(Account, Transaction.account_id == Account.id).where(search_condition)

    sort_column = Transaction.occurred_at if sort_by == "occurred_at" else Transaction.amount_minor
    order = sort_column.asc() if sort_dir == "asc" else sort_column.desc()
    # Вторичный ключ по id — стабильный порядок при равных датах/суммах,
    # иначе пагинация может задвоить или потерять строку между страницами.
    tie_breaker = Transaction.id.asc() if sort_dir == "asc" else Transaction.id.desc()
    stmt = stmt.order_by(order, tie_breaker)

    total = db.scalar(count_stmt) or 0
    response.headers["X-Total-Count"] = str(total)

    stmt = stmt.limit(min(limit, MAX_PAGE_SIZE)).offset(max(offset, 0))
    return [to_out(tx) for tx in db.scalars(stmt).all()]


@router.get("/{transaction_id}", response_model=TransactionOut)
def get_transaction(transaction_id: int, db: Session = Depends(get_db)) -> TransactionOut:
    return to_out(get_transaction_or_404(db, transaction_id))


@router.patch("/{transaction_id}", response_model=TransactionOut)
def update_transaction(
    transaction_id: int, payload: TransactionUpdate, db: Session = Depends(get_db)
) -> TransactionOut:
    tx = get_transaction_or_404(db, transaction_id)
    _reject_if_debt_payment(tx)
    data = payload.model_dump(exclude_unset=True)

    new_type = data.get("type", tx.type)
    if "account_id" in data:
        account = _get_account(db, data["account_id"])
        tx.account_id = account.id
        tx.currency = account.currency
    if "category_id" in data or "type" in data:
        category_id = data.get("category_id", tx.category_id)
        category = _get_category(db, category_id)
        _check_category_matches_type(category, new_type)
        tx.category_id = category.id

    if tx.purpose is not None:
        # Изменение типа или счёта может сделать назначение бессмысленным
        # (доход-«погашение», перевод на тот же счёт) — проверяем заранее.
        try:
            _check_purpose(
                db,
                tx_type=new_type,
                account_id=tx.account_id,
                currency=tx.currency,
                purpose=tx.purpose,
                purpose_account_id=tx.purpose_account_id,
                purpose_debt_id=tx.purpose_debt_id,
            )
        except HTTPException as exc:
            db.rollback()
            raise HTTPException(status_code=400, detail=f"{exc.detail}. {PURPOSE_HINT}") from None

    tx.type = new_type
    if "amount_minor" in data:
        tx.amount_minor = data["amount_minor"]
    if "occurred_at" in data:
        tx.occurred_at = data["occurred_at"]
    if "comment" in data:
        tx.comment = data["comment"]

    db.commit()
    db.refresh(tx)
    return to_out(tx)


@router.patch("/{transaction_id}/purpose", response_model=TransactionOut)
def set_transaction_purpose(
    transaction_id: int, payload: TransactionPurposeUpdate, db: Session = Depends(get_db)
) -> TransactionOut:
    """Ручная классификация (Stage 3F): меняются только поля назначения.
    Сумма, дата, счёт, категория и комментарий остаются прежними; баланс
    счёта не меняется. purpose=null возвращает обычный тип."""
    tx = get_transaction_or_404(db, transaction_id)
    _reject_if_debt_payment(tx)  # платёж по долгу уже учтён как погашение
    _check_purpose(
        db,
        tx_type=tx.type,
        account_id=tx.account_id,
        currency=tx.currency,
        purpose=payload.purpose,
        purpose_account_id=payload.purpose_account_id,
        purpose_debt_id=payload.purpose_debt_id,
    )
    tx.purpose = payload.purpose
    tx.purpose_account_id = payload.purpose_account_id
    tx.purpose_debt_id = payload.purpose_debt_id
    db.commit()
    db.refresh(tx)
    return to_out(tx)


PAIR_WINDOW = timedelta(days=1)
MAX_PAIR_CANDIDATES = 5


@router.get("/{transaction_id}/pair-candidates", response_model=list[TransactionOut])
def pair_candidates(transaction_id: int, db: Session = Depends(get_db)) -> list[TransactionOut]:
    """Возможная вторая сторона перевода между своими счетами: операция
    противоположного типа на другом счёте, та же валюта и сумма, не дальше
    суток по времени, ещё без назначения. Только подсказка — ничего не
    связывается и не меняется без действия пользователя."""
    tx = get_transaction_or_404(db, transaction_id)
    opposite = "income" if tx.type == "expense" else "expense"
    rows = db.scalars(
        select(Transaction).where(
            Transaction.id != tx.id,
            Transaction.type == opposite,
            Transaction.currency == tx.currency,
            Transaction.amount_minor == tx.amount_minor,
            Transaction.account_id != tx.account_id,
            Transaction.purpose.is_(None),
            Transaction.debt_payment_id.is_(None),
            Transaction.occurred_at >= tx.occurred_at - PAIR_WINDOW,
            Transaction.occurred_at <= tx.occurred_at + PAIR_WINDOW,
        )
    ).all()
    rows = sorted(rows, key=lambda r: (abs((r.occurred_at - tx.occurred_at).total_seconds()), r.id))
    return [to_out(r) for r in rows[:MAX_PAIR_CANDIDATES]]


@router.delete("/{transaction_id}", status_code=204)
def delete_transaction(transaction_id: int, db: Session = Depends(get_db)) -> None:
    tx = get_transaction_or_404(db, transaction_id)
    _reject_if_debt_payment(tx)
    db.delete(tx)
    db.commit()
