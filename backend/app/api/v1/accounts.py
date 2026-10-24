"""Счета: банковские, наличные и прочие денежные счета."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Account, DebtPayment, RecurringTransaction, Transaction, Transfer
from app.db.session import get_db
from app.engine.accounts import account_balance
from app.engine.money import Money, get_currency
from app.schemas.accounts import AccountCreate, AccountOut, AccountUpdate
from app.schemas.money import MoneyOut

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _signed_entries(db: Session, account: Account) -> list[Money]:
    """Собирает подписанные суммы всех операций, влияющих на баланс счёта."""
    cur = get_currency(account.currency)
    entries: list[Money] = []

    for tx in db.scalars(
        select(Transaction).where(Transaction.account_id == account.id)
    ):
        amount = Money.of(tx.amount_minor, cur)
        entries.append(amount if tx.type == "income" else -amount)

    for out in db.scalars(
        select(Transfer).where(Transfer.from_account_id == account.id)
    ):
        entries.append(-Money.of(out.amount_minor, cur))

    for inc in db.scalars(
        select(Transfer).where(Transfer.to_account_id == account.id)
    ):
        entries.append(Money.of(inc.amount_minor, cur))

    # Погашение долга здесь намеренно НЕ читается из DebtPayment: платёж,
    # привязанный к счёту, уже представлен связанной Transaction (см.
    # app/api/v1/debts.py) и учтён в первом цикле. Второй цикл по DebtPayment
    # дал бы двойное списание.
    return entries


def compute_balance(db: Session, account: Account) -> Money:
    cur = get_currency(account.currency)
    initial = Money.of(account.initial_balance_minor, cur)
    return account_balance(initial, _signed_entries(db, account))


def to_out(db: Session, account: Account) -> AccountOut:
    balance = compute_balance(db, account)
    return AccountOut(
        id=account.id,
        name=account.name,
        type=account.type,
        currency=account.currency,
        initial_balance_minor=account.initial_balance_minor,
        is_active=account.is_active,
        balance=MoneyOut(minor=balance.minor, currency=balance.currency.code),
    )


def get_account_or_404(db: Session, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Счёт не найден")
    return account


@router.post("", response_model=AccountOut, status_code=201)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)) -> AccountOut:
    currency = get_currency(payload.currency)
    account = Account(
        name=payload.name,
        type=payload.type,
        currency=currency.code,
        initial_balance_minor=payload.initial_balance_minor,
        is_active=payload.is_active,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return to_out(db, account)


@router.get("", response_model=list[AccountOut])
def list_accounts(
    include_inactive: bool = True, db: Session = Depends(get_db)
) -> list[AccountOut]:
    stmt = select(Account).order_by(Account.is_active.desc(), Account.name)
    if not include_inactive:
        stmt = stmt.where(Account.is_active.is_(True))
    accounts = db.scalars(stmt).all()
    return [to_out(db, a) for a in accounts]


@router.get("/{account_id}", response_model=AccountOut)
def get_account(account_id: int, db: Session = Depends(get_db)) -> AccountOut:
    account = get_account_or_404(db, account_id)
    return to_out(db, account)


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(
    account_id: int, payload: AccountUpdate, db: Session = Depends(get_db)
) -> AccountOut:
    account = get_account_or_404(db, account_id)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(account, field, value)
    db.commit()
    db.refresh(account)
    return to_out(db, account)


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: int, db: Session = Depends(get_db)) -> None:
    account = get_account_or_404(db, account_id)
    has_transactions = db.scalar(
        select(Transaction.id).where(Transaction.account_id == account_id).limit(1)
    )
    has_transfers = db.scalar(
        select(Transfer.id)
        .where(
            (Transfer.from_account_id == account_id)
            | (Transfer.to_account_id == account_id)
        )
        .limit(1)
    )
    # Погашение долга может быть привязано к счёту (см. _signed_entries) —
    # это тоже операция, влияющая на баланс, и её тоже нужно проверить,
    # иначе DELETE упадёт с необработанным IntegrityError (500) вместо
    # понятной ошибки: на DebtPayment.account_id есть внешний ключ без
    # ON DELETE CASCADE.
    has_debt_payments = db.scalar(
        select(DebtPayment.id).where(DebtPayment.account_id == account_id).limit(1)
    )
    # Та же причина, что и для DebtPayment выше (Stage 2B): у
    # RecurringTransaction.account_id тоже нет ON DELETE CASCADE — правило
    # должно явно мешать удалению счёта, а не ронять запрос 500-й.
    has_recurring = db.scalar(
        select(RecurringTransaction.id)
        .where(RecurringTransaction.account_id == account_id)
        .limit(1)
    )
    if has_transactions or has_transfers or has_debt_payments or has_recurring:
        raise HTTPException(
            status_code=400,
            detail="У счёта есть операции — удаление запрещено. Деактивируйте счёт вместо удаления.",
        )
    db.delete(account)
    try:
        db.commit()
    except IntegrityError:
        # Защитная сетка на случай ссылки, которую не поймали проверки выше
        # (например, будущая сущность со внешним ключом на accounts.id):
        # пользователь должен увидеть понятную ошибку, а не 500.
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="У счёта есть связанные данные — удаление запрещено. Деактивируйте счёт вместо удаления.",
        ) from None
