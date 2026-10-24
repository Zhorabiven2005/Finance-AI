"""Восстановление состояния приложения из проверенной резервной копии.

Режим — Replace: текущие данные заменяются данными из файла. Безопасность:
  * сюда попадает только документ, уже прошедший validate_backup — значит
    структура, связи и инварианты проверены ДО первого DELETE;
  * удаление старых данных и вставка новых идут в ОДНОЙ транзакции БД;
  * перед COMMIT дополнительно выполняется PRAGMA foreign_key_check;
  * любая ошибка на любом шаге — ROLLBACK, и БД остаётся ровно такой, какой
    была до запроса.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, insert, text
from sqlalchemy.orm import Session

from app.backup.exporter import EXPORT_COLUMNS
from app.backup.format import SECTIONS, BackupDocument
from app.db.models import AppSettings
from app.db.models.app_settings import SINGLETON_ID


class RestoreFailedError(Exception):
    pass


def _rows_for(doc: BackupDocument, section: str) -> list[dict[str, Any]]:
    _, columns = EXPORT_COLUMNS[section]
    records = getattr(doc.data, section)
    if section == "categories":
        # Родители раньше подкатегорий: внешний ключ parent_id проверяется
        # SQLite сразу при вставке строки.
        records = sorted(records, key=lambda c: (c.parent_id is not None, c.id))
    return [
        {"id": r.id, **{c: getattr(r, c) for c in columns}, "created_at": r.created_at, "updated_at": r.updated_at}
        for r in records
    ]


def _insert_rows(db: Session, section: str, rows: list[dict[str, Any]]) -> None:
    if rows:
        model, _ = EXPORT_COLUMNS[section]
        db.execute(insert(model.__table__), rows)  # type: ignore[attr-defined]


def restore_backup(db: Session, doc: BackupDocument) -> dict[str, int]:
    try:
        for section in reversed(SECTIONS):
            model, _ = EXPORT_COLUMNS[section]
            db.execute(delete(model.__table__))  # type: ignore[attr-defined]

        for section in SECTIONS:
            _insert_rows(db, section, _rows_for(doc, section))

        settings_row = db.get(AppSettings, SINGLETON_ID)
        if settings_row is None:
            db.add(
                AppSettings(
                    id=SINGLETON_ID,
                    base_currency=doc.settings.base_currency,
                    locale=doc.settings.locale,
                )
            )
        else:
            settings_row.base_currency = doc.settings.base_currency
            settings_row.locale = doc.settings.locale
        db.flush()

        violations = db.execute(text("PRAGMA foreign_key_check")).fetchall()
        if violations:
            raise RestoreFailedError(f"нарушены внешние ключи: {violations[:3]}")
        db.commit()
    except Exception as e:
        db.rollback()
        raise RestoreFailedError(str(e)) from e
    # ORM-объекты в сессии могли остаться от старого состояния.
    db.expire_all()
    return {section: len(getattr(doc.data, section)) for section in SECTIONS}
