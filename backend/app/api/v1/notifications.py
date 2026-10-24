"""Центр уведомлений. Бизнес-логика генерации — в app/notifications/."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.models import Budget, Debt, Notification, RecurringTransaction
from app.db.session import get_db
from app.notifications.service import NotificationCheckBusy, generate_notifications
from app.schemas.common import ApiModel

router = APIRouter(prefix="/notifications", tags=["notifications"])

LIST_LIMIT = 200
_ENTITY_MODELS = {"debt": Debt, "budget": Budget, "recurring_transaction": RecurringTransaction}


class NotificationOut(ApiModel):
    id: int
    type: str
    severity: str
    title: str
    message: str
    entity_type: str | None
    entity_id: int | None
    entity_exists: bool
    dedup_key: str
    data: dict[str, Any] | None
    created_at: datetime
    read_at: datetime | None
    resolved_at: datetime | None
    is_read: bool
    is_active: bool


class UnreadCountOut(ApiModel):
    unread: int


class CheckOut(ApiModel):
    created: int
    resolved: int
    reactivated: int
    purged: int


def _visible():
    return Notification.deleted_at.is_(None)


def _unread():
    return _visible() & Notification.read_at.is_(None) & Notification.resolved_at.is_(None)


def _entity_exists(db: Session, n: Notification) -> bool:
    if n.entity_type == "analytics":
        return True
    model = _ENTITY_MODELS.get(n.entity_type or "")
    return bool(model and n.entity_id and db.get(model, n.entity_id) is not None)


def to_out(db: Session, n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        type=n.type,
        severity=n.severity,
        title=n.title,
        message=n.message,
        entity_type=n.entity_type,
        entity_id=n.entity_id,
        entity_exists=_entity_exists(db, n),
        dedup_key=n.dedup_key,
        data=json.loads(n.data) if n.data else None,
        created_at=n.created_at,
        read_at=n.read_at,
        resolved_at=n.resolved_at,
        is_read=n.read_at is not None,
        is_active=n.resolved_at is None,
    )


def _get_visible_or_404(db: Session, notification_id: int) -> Notification:
    n = db.get(Notification, notification_id)
    if n is None or n.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")
    return n


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    status: Literal["all", "unread"] = "all", db: Session = Depends(get_db)
) -> list[NotificationOut]:
    stmt = select(Notification).where(_unread() if status == "unread" else _visible())
    # Сначала актуальные, внутри — новые сверху.
    stmt = stmt.order_by(Notification.resolved_at.is_not(None), Notification.created_at.desc(), Notification.id.desc())
    return [to_out(db, n) for n in db.scalars(stmt.limit(LIST_LIMIT))]


@router.get("/unread-count", response_model=UnreadCountOut)
def unread_count(db: Session = Depends(get_db)) -> UnreadCountOut:
    return UnreadCountOut(unread=db.scalar(select(func.count(Notification.id)).where(_unread())) or 0)


@router.post("/read-all", response_model=UnreadCountOut)
def mark_all_read(db: Session = Depends(get_db)) -> UnreadCountOut:
    db.execute(
        update(Notification)
        .where(_visible() & Notification.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )
    db.commit()
    return UnreadCountOut(unread=0)


@router.post("/check", response_model=CheckOut)
def run_check(db: Session = Depends(get_db)) -> CheckOut:
    """Ручная проверка. Идемпотентна: повторный вызов создаёт 0 новых."""
    try:
        return CheckOut(**generate_notifications(db).as_dict())
    except NotificationCheckBusy:
        raise HTTPException(status_code=409, detail="Проверка уже выполняется, попробуйте через минуту.") from None


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: int, db: Session = Depends(get_db)) -> NotificationOut:
    n = _get_visible_or_404(db, notification_id)
    if n.read_at is None:
        n.read_at = datetime.now(timezone.utc)
        db.commit()
    return to_out(db, n)


@router.delete("/{notification_id}", status_code=204)
def delete_notification(notification_id: int, db: Session = Depends(get_db)) -> None:
    """Мягкое удаление: запись с ключом остаётся, и engine не создаст это
    же событие заново."""
    n = _get_visible_or_404(db, notification_id)
    n.deleted_at = datetime.now(timezone.utc)
    if n.read_at is None:
        n.read_at = n.deleted_at
    db.commit()
