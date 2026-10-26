"""Сборка резервной копии из текущей БД (см. формат в app/backup/format.py)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backup.format import BACKUP_FORMAT_NAME, BACKUP_FORMAT_VERSION
from app.db.models import (
    Account,
    AppSettings,
    Budget,
    Category,
    Debt,
    DebtPayment,
    Goal,
    GoalEntry,
    Notification,
    RecurringTransaction,
    RecurringTransactionRun,
    Transaction,
    Transfer,
)
from app.db.models.app_settings import SINGLETON_ID, get_base_currency

# Таблица -> экспортируемые колонки (все колонки модели; id и метки времени
# добавляются ко всем). Перечислены явно, чтобы новая колонка в модели не
# попала в backup незаметно, без изменения формата и его версии.
EXPORT_COLUMNS: dict[str, tuple[type, tuple[str, ...]]] = {
    "accounts": (Account, ("name", "type", "currency", "initial_balance_minor", "is_active")),
    "categories": (Category, ("name", "type", "icon", "parent_id", "is_default", "is_archived")),
    "transactions": (
        Transaction,
        (
            "account_id",
            "category_id",
            "type",
            "amount_minor",
            "currency",
            "occurred_at",
            "comment",
            "debt_payment_id",
            "purpose",
            "purpose_account_id",
            "purpose_debt_id",
        ),
    ),
    "transfers": (
        Transfer,
        ("from_account_id", "to_account_id", "amount_minor", "currency", "occurred_at", "comment"),
    ),
    "debts": (Debt, ("counterparty_name", "direction", "principal_minor", "currency", "due_date", "comment")),
    "debt_payments": (DebtPayment, ("debt_id", "account_id", "amount_minor", "paid_at", "comment")),
    "budgets": (Budget, ("category_id", "amount_minor", "currency", "year", "month")),
    "recurring_transactions": (
        RecurringTransaction,
        (
            "type",
            "account_id",
            "category_id",
            "amount_minor",
            "currency",
            "comment",
            "start_date",
            "end_date",
            "frequency",
            "next_run_date",
            "is_active",
        ),
    ),
    "recurring_transaction_runs": (
        RecurringTransactionRun,
        ("recurring_transaction_id", "run_date", "transaction_id"),
    ),
    "goals": (Goal, ("name", "description", "target_amount_minor", "currency", "target_date", "is_archived")),
    "goal_entries": (GoalEntry, ("goal_id", "amount_minor", "type", "occurred_at", "comment")),
    "notifications": (
        Notification,
        (
            "type",
            "severity",
            "title",
            "message",
            "entity_type",
            "entity_id",
            "dedup_key",
            "data",
            "read_at",
            "resolved_at",
            "deleted_at",
        ),
    ),
}


def iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return iso_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _rows(db: Session, model: type, columns: tuple[str, ...]) -> list[dict[str, Any]]:
    out = []
    for obj in db.scalars(select(model).order_by(model.id)):  # type: ignore[attr-defined]
        row = {"id": obj.id}
        for col in columns:
            row[col] = _serialize(getattr(obj, col))
        row["created_at"] = _serialize(obj.created_at)
        row["updated_at"] = _serialize(obj.updated_at)
        out.append(row)
    return out


def build_backup(db: Session, now: datetime | None = None) -> dict[str, Any]:
    exported_at = now or datetime.now(timezone.utc)
    settings_row = db.get(AppSettings, SINGLETON_ID)
    base_currency = get_base_currency(db)
    return {
        "format": BACKUP_FORMAT_NAME,
        "version": BACKUP_FORMAT_VERSION,
        "exported_at": iso_utc(exported_at),
        "base_currency": base_currency,
        "settings": {
            "base_currency": base_currency,
            "locale": settings_row.locale if settings_row else "ru-RU",
        },
        "data": {
            section: _rows(db, model, columns)
            for section, (model, columns) in EXPORT_COLUMNS.items()
        },
    }
