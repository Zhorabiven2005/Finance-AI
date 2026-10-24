"""Финансовые цели: планировочная сущность, независимая от счетов.

saved считается заново при каждом запросе из GoalEntry — не кешируется,
тем же принципом, что и баланс счёта, остаток долга, расход по бюджету
(см. app/engine/goals.py и docstring в app/db/models/goal.py).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Goal, GoalEntry
from app.db.session import get_db
from app.engine.goals import calculate_goal_progress, calculate_goal_remaining, calculate_goal_status
from app.engine.money import Money, get_currency, money_sum
from app.schemas.goals import GoalCreate, GoalEntryCreate, GoalEntryOut, GoalOut, GoalUpdate
from app.schemas.money import MoneyOut

router = APIRouter(prefix="/goals", tags=["goals"])


def _saved_amount(goal: Goal) -> Money:
    cur = get_currency(goal.currency)
    contributions = (
        Money.of(e.amount_minor, cur) for e in goal.entries if e.type == "contribution"
    )
    withdrawals = (
        Money.of(e.amount_minor, cur) for e in goal.entries if e.type == "withdrawal"
    )
    return money_sum(contributions, cur) - money_sum(withdrawals, cur)


def to_out(goal: Goal) -> GoalOut:
    cur = get_currency(goal.currency)
    target = Money.of(goal.target_amount_minor, cur)
    saved = _saved_amount(goal)
    remaining = calculate_goal_remaining(target, saved)
    progress = calculate_goal_progress(saved, target)
    status = calculate_goal_status(saved, target, goal.is_archived)
    return GoalOut(
        id=goal.id,
        name=goal.name,
        description=goal.description,
        target=MoneyOut(minor=target.minor, currency=cur.code),
        saved=MoneyOut(minor=saved.minor, currency=cur.code),
        remaining=MoneyOut(minor=remaining.minor, currency=cur.code),
        progress_percent=float(progress),
        currency=cur.code,
        target_date=goal.target_date,
        status=status.value,  # type: ignore[arg-type]
        created_at=goal.created_at,
    )


def entry_to_out(entry: GoalEntry, currency: str) -> GoalEntryOut:
    return GoalEntryOut(
        id=entry.id,
        goal_id=entry.goal_id,
        type=entry.type,  # type: ignore[arg-type]
        amount=MoneyOut(minor=entry.amount_minor, currency=currency),
        occurred_at=entry.occurred_at,
        comment=entry.comment,
    )


def get_goal_or_404(db: Session, goal_id: int) -> Goal:
    goal = db.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Цель не найдена")
    return goal


@router.post("", response_model=GoalOut, status_code=201)
def create_goal(payload: GoalCreate, db: Session = Depends(get_db)) -> GoalOut:
    currency = get_currency(payload.currency)
    goal = Goal(
        name=payload.name.strip(),
        description=payload.description,
        target_amount_minor=payload.target_amount_minor,
        currency=currency.code,
        target_date=payload.target_date,
        is_archived=False,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return to_out(goal)


@router.get("", response_model=list[GoalOut])
def list_goals(
    include_archived: bool = True, db: Session = Depends(get_db)
) -> list[GoalOut]:
    stmt = select(Goal).order_by(Goal.created_at.desc())
    if not include_archived:
        stmt = stmt.where(Goal.is_archived.is_(False))
    return [to_out(g) for g in db.scalars(stmt).all()]


@router.get("/{goal_id}", response_model=GoalOut)
def get_goal(goal_id: int, db: Session = Depends(get_db)) -> GoalOut:
    return to_out(get_goal_or_404(db, goal_id))


@router.patch("/{goal_id}", response_model=GoalOut)
def update_goal(goal_id: int, payload: GoalUpdate, db: Session = Depends(get_db)) -> GoalOut:
    goal = get_goal_or_404(db, goal_id)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(goal, field, value)
    db.commit()
    db.refresh(goal)
    return to_out(goal)


@router.delete("/{goal_id}", status_code=204)
def delete_goal(goal_id: int, db: Session = Depends(get_db)) -> None:
    # Удаляет и историю накоплений (GoalEntry) каскадом — в отличие от
    # RecurringTransaction, у цели нет "независимых" последствий вовне:
    # GoalEntry существует только для отслеживания прогресса этой цели.
    goal = get_goal_or_404(db, goal_id)
    db.delete(goal)
    db.commit()


@router.post("/{goal_id}/entries", response_model=GoalEntryOut, status_code=201)
def add_goal_entry(
    goal_id: int, payload: GoalEntryCreate, db: Session = Depends(get_db)
) -> GoalEntryOut:
    goal = get_goal_or_404(db, goal_id)

    if payload.type == "withdrawal":
        cur = get_currency(goal.currency)
        saved = _saved_amount(goal)
        amount = Money.of(payload.amount_minor, cur)
        if amount.minor > saved.minor:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Нельзя снять больше накопленного: остаток {saved.format()}, "
                    f"запрошено {amount.format()}"
                ),
            )

    entry = GoalEntry(
        goal_id=goal.id,
        amount_minor=payload.amount_minor,
        type=payload.type,
        occurred_at=payload.occurred_at,
        comment=payload.comment,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry_to_out(entry, goal.currency)


@router.get("/{goal_id}/entries", response_model=list[GoalEntryOut])
def list_goal_entries(goal_id: int, db: Session = Depends(get_db)) -> list[GoalEntryOut]:
    goal = get_goal_or_404(db, goal_id)
    ordered = sorted(goal.entries, key=lambda e: e.occurred_at, reverse=True)
    return [entry_to_out(e, goal.currency) for e in ordered]


@router.delete("/{goal_id}/entries/{entry_id}", status_code=204)
def delete_goal_entry(goal_id: int, entry_id: int, db: Session = Depends(get_db)) -> None:
    entry = db.get(GoalEntry, entry_id)
    if entry is None or entry.goal_id != goal_id:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    db.delete(entry)
    db.commit()
