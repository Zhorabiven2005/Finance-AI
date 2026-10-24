"""Категории доходов и расходов.

Дерево категорий ограничено одним уровнем (категория → подкатегория, без
внуков) — проверяется здесь, а не CHECK-constraint'ом в БД: SQLite не
умеет выразить "у родителя нет своего родителя" через ограничение над той
же таблицей.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Budget, Category, RecurringTransaction, Transaction
from app.db.session import get_db
from app.schemas.categories import CategoryCreate, CategoryOut, CategoryUpdate

router = APIRouter(prefix="/categories", tags=["categories"])


def get_category_or_404(db: Session, category_id: int) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    return category


def _check_parent_depth(parent: Category) -> None:
    if parent.parent_id is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Нельзя создать подкатегорию у подкатегории — "
                "поддерживается только один уровень вложенности"
            ),
        )


def _check_no_children(db: Session, category: Category) -> None:
    has_children = db.scalar(
        select(Category.id).where(Category.parent_id == category.id).limit(1)
    )
    if has_children:
        raise HTTPException(
            status_code=400,
            detail="У категории уже есть подкатегории — она не может сама стать подкатегорией",
        )


def _is_used_in_transactions(db: Session, category_id: int) -> bool:
    return (
        db.scalar(select(Transaction.id).where(Transaction.category_id == category_id).limit(1))
        is not None
    )


@router.post("", response_model=CategoryOut, status_code=201)
def create_category(payload: CategoryCreate, db: Session = Depends(get_db)) -> CategoryOut:
    if payload.parent_id is not None:
        parent = get_category_or_404(db, payload.parent_id)
        if parent.type != payload.type:
            raise HTTPException(
                status_code=400,
                detail="Тип подкатегории должен совпадать с типом родительской категории",
            )
        _check_parent_depth(parent)

    # Сравнение регистронезависимо и в Python, а не через SQL LOWER(): в
    # SQLite эта функция по умолчанию приводит к нижнему регистру только
    # ASCII, кириллица остаётся как есть, и "Хобби" не считался бы
    # дубликатом "хобби".
    target_name = payload.name.strip().casefold()
    existing_names = db.scalars(
        select(Category.name).where(Category.type == payload.type)
    ).all()
    if any(name.casefold() == target_name for name in existing_names):
        raise HTTPException(
            status_code=400, detail="Категория с таким названием и типом уже существует"
        )

    category = Category(
        name=payload.name.strip(),
        type=payload.type,
        icon=payload.icon,
        parent_id=payload.parent_id,
        is_default=False,
        is_archived=False,
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@router.get("", response_model=list[CategoryOut])
def list_categories(
    type: str | None = None,
    include_archived: bool = False,
    db: Session = Depends(get_db),
) -> list[Category]:
    stmt = select(Category).order_by(Category.type, Category.name)
    if type is not None:
        stmt = stmt.where(Category.type == type)
    if not include_archived:
        stmt = stmt.where(Category.is_archived.is_(False))
    return list(db.scalars(stmt).all())


@router.get("/{category_id}", response_model=CategoryOut)
def get_category(category_id: int, db: Session = Depends(get_db)) -> Category:
    return get_category_or_404(db, category_id)


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: int, payload: CategoryUpdate, db: Session = Depends(get_db)
) -> Category:
    category = get_category_or_404(db, category_id)
    data = payload.model_dump(exclude_unset=True)

    new_type = data.get("type", category.type)
    if "type" in data and data["type"] != category.type:
        if _is_used_in_transactions(db, category_id):
            raise HTTPException(
                status_code=400,
                detail="Нельзя изменить тип категории, которая уже используется в операциях",
            )
        _check_no_children(db, category)
        if category.parent_id is not None:
            parent = get_category_or_404(db, category.parent_id)
            if parent.type != new_type:
                raise HTTPException(
                    status_code=400,
                    detail="Тип подкатегории должен совпадать с типом родительской категории",
                )

    if "parent_id" in data and data["parent_id"] is not None:
        parent = get_category_or_404(db, data["parent_id"])
        if parent.type != new_type:
            raise HTTPException(
                status_code=400,
                detail="Тип подкатегории должен совпадать с типом родительской категории",
            )
        if parent.id == category.id:
            raise HTTPException(
                status_code=400, detail="Категория не может быть родителем самой себя"
            )
        _check_parent_depth(parent)
        _check_no_children(db, category)

    for field, value in data.items():
        setattr(category, field, value)
    db.commit()
    db.refresh(category)
    return category


@router.delete("/{category_id}", status_code=204)
def delete_category(category_id: int, db: Session = Depends(get_db)) -> None:
    category = get_category_or_404(db, category_id)
    if category.is_default:
        raise HTTPException(status_code=400, detail="Базовую категорию нельзя удалить")
    if _is_used_in_transactions(db, category_id):
        raise HTTPException(
            status_code=400,
            detail="Категория используется в операциях — удаление запрещено. Архивируйте её вместо удаления.",
        )
    has_children = db.scalar(
        select(Category.id).where(Category.parent_id == category_id).limit(1)
    )
    if has_children:
        raise HTTPException(
            status_code=400, detail="У категории есть подкатегории — удаление запрещено"
        )
    # Budget/RecurringTransaction.category_id тоже без ON DELETE CASCADE
    # (Stage 2B) — без этой проверки удаление упало бы 500-й вместо
    # понятной ошибки, та же причина, что и для in_use выше.
    has_budget = db.scalar(
        select(Budget.id).where(Budget.category_id == category_id).limit(1)
    )
    if has_budget:
        raise HTTPException(
            status_code=400,
            detail="У категории есть бюджет — удаление запрещено. Архивируйте её вместо удаления.",
        )
    has_recurring = db.scalar(
        select(RecurringTransaction.id)
        .where(RecurringTransaction.category_id == category_id)
        .limit(1)
    )
    if has_recurring:
        raise HTTPException(
            status_code=400,
            detail=(
                "Категория используется в регулярной операции — удаление запрещено. "
                "Архивируйте её вместо удаления."
            ),
        )
    db.delete(category)
    db.commit()
