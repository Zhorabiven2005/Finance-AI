"""Переводы между своими счетами.

Перевод не считается доходом или расходом — у него нет категории, и он не
попадает в статистику доходов/расходов. Баланс счетов, как и для обычных
операций, всегда выводится заново (см. app/api/v1/accounts.py).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Account, Transfer
from app.db.session import get_db
from app.schemas.money import MoneyOut
from app.schemas.transfers import TransferCreate, TransferOut, TransferUpdate

router = APIRouter(prefix="/transfers", tags=["transfers"])


def to_out(tr: Transfer) -> TransferOut:
    return TransferOut(
        id=tr.id,
        from_account_id=tr.from_account_id,
        to_account_id=tr.to_account_id,
        amount=MoneyOut(minor=tr.amount_minor, currency=tr.currency),
        occurred_at=tr.occurred_at,
        comment=tr.comment,
    )


def _get_account(db: Session, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Счёт не найден")
    return account


def get_transfer_or_404(db: Session, transfer_id: int) -> Transfer:
    tr = db.get(Transfer, transfer_id)
    if tr is None:
        raise HTTPException(status_code=404, detail="Перевод не найден")
    return tr


@router.post("", response_model=TransferOut, status_code=201)
def create_transfer(payload: TransferCreate, db: Session = Depends(get_db)) -> TransferOut:
    if payload.from_account_id == payload.to_account_id:
        raise HTTPException(
            status_code=400, detail="Счёт-источник и счёт-получатель должны различаться"
        )
    from_account = _get_account(db, payload.from_account_id)
    to_account = _get_account(db, payload.to_account_id)
    if from_account.currency != to_account.currency:
        raise HTTPException(
            status_code=400,
            detail="Перевод между счетами в разных валютах пока не поддерживается",
        )

    tr = Transfer(
        from_account_id=from_account.id,
        to_account_id=to_account.id,
        amount_minor=payload.amount_minor,
        currency=from_account.currency,
        occurred_at=payload.occurred_at,
        comment=payload.comment,
    )
    db.add(tr)
    db.commit()
    db.refresh(tr)
    return to_out(tr)


@router.get("", response_model=list[TransferOut])
def list_transfers(
    account_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[TransferOut]:
    stmt = select(Transfer).order_by(Transfer.occurred_at.desc(), Transfer.id.desc())
    if account_id is not None:
        stmt = stmt.where(
            (Transfer.from_account_id == account_id)
            | (Transfer.to_account_id == account_id)
        )
    if date_from is not None:
        stmt = stmt.where(Transfer.occurred_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Transfer.occurred_at <= date_to)
    stmt = stmt.limit(min(limit, 500)).offset(offset)
    return [to_out(tr) for tr in db.scalars(stmt).all()]


@router.get("/{transfer_id}", response_model=TransferOut)
def get_transfer(transfer_id: int, db: Session = Depends(get_db)) -> TransferOut:
    return to_out(get_transfer_or_404(db, transfer_id))


@router.patch("/{transfer_id}", response_model=TransferOut)
def update_transfer(
    transfer_id: int, payload: TransferUpdate, db: Session = Depends(get_db)
) -> TransferOut:
    tr = get_transfer_or_404(db, transfer_id)
    data = payload.model_dump(exclude_unset=True)
    if "amount_minor" in data:
        tr.amount_minor = data["amount_minor"]
    if "occurred_at" in data:
        tr.occurred_at = data["occurred_at"]
    if "comment" in data:
        tr.comment = data["comment"]
    db.commit()
    db.refresh(tr)
    return to_out(tr)


@router.delete("/{transfer_id}", status_code=204)
def delete_transfer(transfer_id: int, db: Session = Depends(get_db)) -> None:
    tr = get_transfer_or_404(db, transfer_id)
    db.delete(tr)
    db.commit()
