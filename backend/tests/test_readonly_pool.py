"""Регрессия: read-only сессия не оставляет соединение пула в режиме
«только чтение» (Stage 3F).

Ошибка: get_readonly_db включал PRAGMA query_only на соединении, затем делал
rollback — сессия возвращала соединение в пул — и только потом снимал режим
через db.connection(), то есть уже на ДРУГОМ соединении из пула. Первое
оставалось read-only, и следующая запись на нём падала: «attempt to write a
readonly database». Тесты с StaticPool (одно соединение) этого не видели.

Здесь — настоящий файл SQLite во временном каталоге и QueuePool из
нескольких соединений, как у приложения. Основная БД не используется.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from app.db import session as session_module
from app.db.readonly import ReadOnlySessionError, _block_flush, get_readonly_db

POOL_SIZE = 3
MAIN_DB = (Path(__file__).resolve().parents[1] / "data" / "finance.db").resolve()


def make_engine(path: Path, *, checkin_reset: bool) -> Engine:
    assert path.resolve() != MAIN_DB
    engine = create_engine(
        f"sqlite:///{path}",
        poolclass=QueuePool,
        pool_size=POOL_SIZE,
        max_overflow=0,
        connect_args={"check_same_thread": False},
    )
    event.listen(engine, "connect", session_module._configure_sqlite)
    if checkin_reset:
        event.listen(engine, "checkin", session_module._reset_query_only)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)")
    # Наполняем пул несколькими простаивающими соединениями: так rollback и
    # повторный db.connection() гарантированно получают разные соединения.
    held = [engine.connect() for _ in range(POOL_SIZE)]
    for c in held:
        c.close()
    return engine


def query_only_flags(engine: Engine) -> list[int]:
    """PRAGMA query_only каждого соединения пула (берём все сразу)."""
    held = [engine.connect() for _ in range(POOL_SIZE)]
    try:
        return [c.exec_driver_sql("PRAGMA query_only").scalar() for c in held]
    finally:
        for c in held:
            c.close()


def read_through(dependency, db: Session, *, fail: bool = False) -> None:
    """Проходит зависимость так же, как FastAPI: next(), работа, закрытие."""
    gen = dependency(db)
    s = next(gen)
    s.execute(text("SELECT count(*) FROM t")).scalar()
    if fail:
        with pytest.raises(RuntimeError):
            gen.throw(RuntimeError("ошибка обработчика"))
    else:
        with pytest.raises(StopIteration):
            next(gen)
    db.close()


def write_everywhere(engine: Engine) -> None:
    """Запись через каждое соединение пула — как следующие запросы приложения."""
    Factory = sessionmaker(bind=engine)
    sessions = [Factory() for _ in range(POOL_SIZE)]
    try:
        for i, s in enumerate(sessions):
            s.execute(text("INSERT INTO t (v) VALUES (:v)"), {"v": f"запись {i}"})
            s.commit()
    finally:
        for s in sessions:
            s.close()


def old_get_readonly_db(db: Session):
    """Прежняя реализация (до исправления) — только для контрольной проверки."""
    db.connection().exec_driver_sql("PRAGMA query_only = ON")
    event.listen(db, "before_flush", _block_flush)
    try:
        yield db
    finally:
        event.remove(db, "before_flush", _block_flush)
        db.rollback()
        db.connection().exec_driver_sql("PRAGMA query_only = OFF")
        db.rollback()


def test_control_old_algorithm_leaves_connection_read_only(tmp_path):
    """Контроль: сценарий действительно воспроизводит ошибку."""
    engine = make_engine(tmp_path / "old.db", checkin_reset=False)
    read_through(old_get_readonly_db, Session(bind=engine))
    assert 1 in query_only_flags(engine)
    with pytest.raises(Exception, match="readonly database"):
        write_everywhere(engine)
    engine.dispose()


@pytest.mark.parametrize("fail", [False, True], ids=["обычный запрос", "ошибка обработчика"])
def test_fixed_dependency_releases_read_only(tmp_path, fail):
    """Исправленная зависимость сама снимает режим на том же соединении —
    даже без запасной линии в пуле."""
    engine = make_engine(tmp_path / "fixed.db", checkin_reset=False)
    for _ in range(POOL_SIZE + 1):
        read_through(get_readonly_db, Session(bind=engine), fail=fail)
    assert query_only_flags(engine) == [0] * POOL_SIZE
    write_everywhere(engine)
    engine.dispose()


def test_checkin_reset_is_a_safety_net(tmp_path):
    """Запасная линия: даже старый алгоритм не оставляет read-only соединение,
    если при возврате в пул режим сбрасывается (как у движка приложения)."""
    engine = make_engine(tmp_path / "net.db", checkin_reset=True)
    read_through(old_get_readonly_db, Session(bind=engine))
    assert query_only_flags(engine) == [0] * POOL_SIZE
    write_everywhere(engine)
    engine.dispose()


def test_still_read_only_inside_request(tmp_path):
    """Защита на время запроса сохранилась: писать в read-only сессии нельзя."""
    engine = make_engine(tmp_path / "guard.db", checkin_reset=True)
    gen = get_readonly_db(Session(bind=engine))
    db = next(gen)
    with pytest.raises(Exception, match="readonly database|read-only|только для чтения"):
        db.execute(text("INSERT INTO t (v) VALUES ('нельзя')"))
    gen.close()
    write_everywhere(engine)  # после запроса — снова можно
    engine.dispose()


def test_app_engine_has_checkin_reset():
    """Движок приложения действительно слушает checkin."""
    assert event.contains(session_module.engine, "checkin", session_module._reset_query_only)


def test_orm_flush_blocked_inside_request(tmp_path):
    engine = make_engine(tmp_path / "orm.db", checkin_reset=True)
    gen = get_readonly_db(Session(bind=engine))
    db = next(gen)
    from app.db.models import Account  # noqa: PLC0415

    db.add(Account(name="x", type="bank", currency="RUB", initial_balance_minor=0, is_active=True))
    with pytest.raises(ReadOnlySessionError):
        db.flush()
    gen.close()
    engine.dispose()
