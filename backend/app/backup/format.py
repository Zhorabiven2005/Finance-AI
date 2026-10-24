"""Формат резервной копии Finance AI (логический JSON, не копия SQLite).

Версия формата задаётся ТОЛЬКО здесь (BACKUP_FORMAT_VERSION). Любое
несовместимое изменение структуры — новая версия; файлы неизвестных версий
не импортируются (угадывать структуру нельзя).

История версий:
  * 1 — Stage 2D;
  * 2 — Stage 2E: добавлен раздел data.notifications. Экспорт пишет 2;
    файлы версии 1 по-прежнему импортируются (уведомлений в них нет —
    после восстановления их заново создаст проверка уведомлений).

Структура (version 2):

    {
      "format": "finance-ai-backup",
      "version": 1,
      "exported_at": "2026-10-08T09:00:00Z",      # UTC, ISO 8601
      "base_currency": "RUB",
      "settings": {"base_currency": "RUB", "locale": "ru-RU"},
      "data": {
        "accounts": [...], "categories": [...], "transactions": [...],
        "transfers": [...], "debts": [...], "debt_payments": [...],
        "budgets": [...], "recurring_transactions": [...],
        "recurring_transaction_runs": [...], "goals": [...], "goal_entries": [...],
        "notifications": [...]           # только с version 2
      }
    }

Правила полей:
  * у каждой записи — исходный id, по нему восстанавливаются связи;
  * деньги — только целые минорные единицы (*_minor) плюс currency, без float;
  * datetime — ISO 8601 с часовым поясом (экспорт пишет UTC с "Z"),
    date — "YYYY-MM-DD";
  * неизвестные поля запрещены, обязательные — обязательны (strict-схема ниже).

Модели здесь — схема для валидации импорта; экспорт строит те же поля
(см. app/backup/exporter.py), тест сверяет экспорт с этой схемой.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.db.models.notification import NOTIFICATION_ENTITY_TYPES, NOTIFICATION_SEVERITIES, NOTIFICATION_TYPES

BACKUP_FORMAT_NAME = "finance-ai-backup"
BACKUP_FORMAT_VERSION = 2
SUPPORTED_BACKUP_VERSIONS = frozenset({1, BACKUP_FORMAT_VERSION})

# Лимиты против случайно (или намеренно) огромных файлов.
MAX_BACKUP_BYTES = 25 * 1024 * 1024
MAX_BACKUP_RECORDS = 200_000

# Потолок суммы: заведомо больше любых личных финансов и далеко от
# переполнения 64-битного INTEGER SQLite.
MAX_MINOR = 10**15
MAX_ID = 2**62

Id = Field(gt=0, le=MAX_ID)
MinorPositive = Field(gt=0, le=MAX_MINOR)
Currency = Field(min_length=3, max_length=3)


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: int = Id
    created_at: AwareDatetime
    updated_at: AwareDatetime


class AccountRecord(_Record):
    name: str = Field(min_length=1, max_length=100)
    type: Literal["bank", "cash", "other"]
    currency: str = Currency
    initial_balance_minor: int = Field(ge=-MAX_MINOR, le=MAX_MINOR)
    is_active: bool


class CategoryRecord(_Record):
    name: str = Field(min_length=1, max_length=100)
    type: Literal["income", "expense"]
    icon: str | None = Field(max_length=50)
    parent_id: int | None = Field(gt=0, le=MAX_ID)
    is_default: bool
    is_archived: bool


class TransactionRecord(_Record):
    account_id: int = Id
    category_id: int = Id
    type: Literal["income", "expense"]
    amount_minor: int = MinorPositive
    currency: str = Currency
    occurred_at: AwareDatetime
    comment: str | None = Field(max_length=500)
    debt_payment_id: int | None = Field(gt=0, le=MAX_ID)


class TransferRecord(_Record):
    from_account_id: int = Id
    to_account_id: int = Id
    amount_minor: int = MinorPositive
    currency: str = Currency
    occurred_at: AwareDatetime
    comment: str | None = Field(max_length=500)


class DebtRecord(_Record):
    counterparty_name: str = Field(min_length=1, max_length=200)
    direction: Literal["i_owe", "owed_to_me"]
    principal_minor: int = MinorPositive
    currency: str = Currency
    due_date: date | None
    comment: str | None = Field(max_length=500)


class DebtPaymentRecord(_Record):
    debt_id: int = Id
    account_id: int | None = Field(gt=0, le=MAX_ID)
    amount_minor: int = MinorPositive
    paid_at: AwareDatetime
    comment: str | None = Field(max_length=500)


class BudgetRecord(_Record):
    category_id: int = Id
    amount_minor: int = MinorPositive
    currency: str = Currency
    year: int = Field(ge=1900, le=9999)
    month: int = Field(ge=1, le=12)


class RecurringTransactionRecord(_Record):
    type: Literal["income", "expense"]
    account_id: int = Id
    category_id: int = Id
    amount_minor: int = MinorPositive
    currency: str = Currency
    comment: str | None = Field(max_length=500)
    start_date: date
    end_date: date | None
    frequency: Literal["daily", "weekly", "monthly", "yearly"]
    next_run_date: date
    is_active: bool


class RecurringTransactionRunRecord(_Record):
    recurring_transaction_id: int = Id
    run_date: date
    transaction_id: int = Id


class GoalRecord(_Record):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(max_length=1000)
    target_amount_minor: int = MinorPositive
    currency: str = Currency
    target_date: date | None
    is_archived: bool


class GoalEntryRecord(_Record):
    goal_id: int = Id
    amount_minor: int = MinorPositive
    type: Literal["contribution", "withdrawal"]
    occurred_at: AwareDatetime
    comment: str | None = Field(max_length=500)


NotificationType = Literal[NOTIFICATION_TYPES]  # type: ignore[valid-type]
NotificationSeverity = Literal[NOTIFICATION_SEVERITIES]  # type: ignore[valid-type]
NotificationEntityType = Literal[NOTIFICATION_ENTITY_TYPES]  # type: ignore[valid-type]


class NotificationRecord(_Record):
    type: NotificationType
    severity: NotificationSeverity
    title: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=1000)
    entity_type: NotificationEntityType | None
    entity_id: int | None = Field(gt=0, le=MAX_ID)
    dedup_key: str = Field(min_length=1, max_length=200)
    data: str | None = Field(max_length=10_000)
    read_at: AwareDatetime | None
    resolved_at: AwareDatetime | None
    deleted_at: AwareDatetime | None


class BackupSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    base_currency: str = Currency
    locale: str = Field(min_length=1, max_length=10)


class BackupDataV1(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    accounts: list[AccountRecord]
    categories: list[CategoryRecord]
    transactions: list[TransactionRecord]
    transfers: list[TransferRecord]
    debts: list[DebtRecord]
    debt_payments: list[DebtPaymentRecord]
    budgets: list[BudgetRecord]
    recurring_transactions: list[RecurringTransactionRecord]
    recurring_transaction_runs: list[RecurringTransactionRunRecord]
    goals: list[GoalRecord]
    goal_entries: list[GoalEntryRecord]


class BackupData(BackupDataV1):
    notifications: list[NotificationRecord]


class BackupDocumentV1(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    format: Literal["finance-ai-backup"]
    version: Literal[1]
    exported_at: AwareDatetime
    base_currency: str = Currency
    settings: BackupSettings
    data: BackupDataV1


class BackupDocument(BaseModel):
    """Текущая версия. Документ версии 1 после проверки приводится к этой
    модели с пустым списком уведомлений (см. validator.validate_backup)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    format: Literal["finance-ai-backup"]
    version: Literal[1, 2]
    exported_at: AwareDatetime
    base_currency: str = Currency
    settings: BackupSettings
    data: BackupData


# Порядок вставки при восстановлении: каждая таблица идёт после тех, на
# которые ссылается. Удаление — в обратном порядке.
SECTIONS: tuple[str, ...] = (
    "accounts",
    "categories",
    "debts",
    "debt_payments",
    "transactions",
    "transfers",
    "budgets",
    "recurring_transactions",
    "recurring_transaction_runs",
    "goals",
    "goal_entries",
    "notifications",
)

SECTION_LABELS: dict[str, str] = {
    "accounts": "Счета",
    "categories": "Категории",
    "transactions": "Операции",
    "transfers": "Переводы",
    "debts": "Долги",
    "debt_payments": "Платежи по долгам",
    "budgets": "Бюджеты",
    "recurring_transactions": "Регулярные операции",
    "recurring_transaction_runs": "Запуски регулярных операций",
    "goals": "Цели",
    "goal_entries": "Записи целей",
    "notifications": "Уведомления",
}
