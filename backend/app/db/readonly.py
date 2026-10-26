"""Сессия только для чтения (Stage 2F, финансовый контекст).

Две независимые линии защиты на время запроса:
  * PRAGMA query_only = ON — SQLite сам отклоняет любую запись на этом
    соединении («attempt to write a readonly database»);
  * слушатель before_flush — ORM не даст даже начать запись.

Зависимость построена поверх get_db, поэтому тестовая подмена get_db
(tests/conftest.py) действует и здесь. В finally соединение обязательно
возвращается в обычный режим: оно уходит обратно в пул (а в тестах это
вообще общая сессия), и следующий запрос должен уметь писать.
"""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.db.session import get_db


class ReadOnlySessionError(RuntimeError):
    """Попытка записи через сессию, открытую только для чтения."""


def _block_flush(session: Session, _flush_context, _instances) -> None:
    raise ReadOnlySessionError("Сессия открыта только для чтения: запись запрещена")


def get_readonly_db(db: Session = Depends(get_db)) -> Generator[Session, None, None]:
    db.connection().exec_driver_sql("PRAGMA query_only = ON")
    event.listen(db, "before_flush", _block_flush)
    try:
        yield db
    finally:
        event.remove(db, "before_flush", _block_flush)
        # PRAGMA query_only — настройка соединения, а не транзакции: она
        # действует и после rollback. Снимать её нужно на ТОМ ЖЕ соединении,
        # то есть до rollback: после rollback сессия отдаёт соединение в пул,
        # и db.connection() взяло бы из пула другое — а это осталось бы
        # read-only, и следующая запись на нём упала бы («attempt to write a
        # readonly database»). Если транзакция уже в состоянии ошибки и
        # соединение недоступно, режим снимет сброс при возврате в пул
        # (app/db/session.py, _reset_query_only).
        try:
            db.connection().exec_driver_sql("PRAGMA query_only = OFF")
        except Exception:  # noqa: BLE001 — запасная линия ниже
            pass
        db.rollback()
