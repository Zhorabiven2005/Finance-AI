"""Read-only защита финансового контекста (Stage 2F).

Проверяется на двух конфигурациях:
  * обычная тестовая (in-memory SQLite, одна общая сессия — tests/conftest.py);
  * файловая SQLite во временной папке теста с теми же настройками
    соединения, что у основного движка (WAL, foreign_keys, busy_timeout), и
    новой сессией на каждый запрос, как в app.db.session.get_db.

Основная backend/data/finance.db здесь не используется.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Generator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import app.db.models  # noqa: F401
from app import clock
from app.db import session as session_module
from app.db.base import Base
from app.db.models import Account, Notification
from app.db.readonly import ReadOnlySessionError, get_readonly_db
from app.db.seed import ensure_default_categories
from app.db.session import get_db
from app.main import app

TODAY = date(2026, 10, 17)
APP_DIR = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture(autouse=True)
def fixed_dates(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    monkeypatch.setattr(clock, "utc_today", lambda: TODAY)


def raw_connection(db: Session):
    return db.connection().connection.driver_connection


def populate(client: TestClient) -> None:
    """Данные, на которых генерация уведомлений создала бы записи."""
    acc = client.post("/api/v1/accounts", json={"name": "Карта", "type": "bank", "currency": "RUB", "initial_balance_minor": 100_000}).json()
    debt = client.post("/api/v1/debts", json={"counterparty_name": "Банк", "direction": "i_owe", "principal_minor": 50_000, "currency": "RUB", "due_date": "2026-10-01"}).json()
    client.post(f"/api/v1/debts/{debt['id']}/payments", json={"amount_minor": 10_000, "paid_at": "2026-10-02T10:00:00Z", "account_id": acc["id"]})
    cats = client.get("/api/v1/categories").json()
    food = next(c["id"] for c in cats if c["name"] == "Продукты")
    client.post("/api/v1/recurring-transactions", json={"type": "expense", "account_id": acc["id"], "category_id": food, "amount_minor": 1_000, "start_date": "2026-10-10", "frequency": "monthly"})


class TestSharedTestSession:
    def test_context_writes_nothing_and_creates_no_notifications(self, seeded_client, db_session):
        populate(seeded_client)
        conn = raw_connection(db_session)
        changes = conn.total_changes
        counts = {t: db_session.scalar(text(f"select count(*) from {t}")) for t in ("transactions", "notifications", "recurring_transactions")}
        assert seeded_client.get("/api/v1/context").status_code == 200
        assert seeded_client.get("/api/v1/context").status_code == 200
        assert raw_connection(db_session).total_changes == changes
        assert {t: db_session.scalar(text(f"select count(*) from {t}")) for t in counts} == counts
        assert counts["notifications"] == 0
        # Сценарий содержательный: явная проверка уведомлений их создала бы.
        assert seeded_client.post("/api/v1/notifications/check").json()["created"] >= 1

    def test_regular_writes_work_after_context(self, seeded_client, db_session):
        assert seeded_client.get("/api/v1/context").status_code == 200
        assert db_session.scalar(text("PRAGMA query_only")) == 0
        r = seeded_client.post("/api/v1/accounts", json={"name": "После", "type": "cash", "currency": "RUB", "initial_balance_minor": 0})
        assert r.status_code == 201
        assert seeded_client.get("/api/v1/context").json()["accounts"]["items"][0]["label"] == "После"

    def test_writes_are_blocked_inside_readonly_session(self, seeded_client, db_session):
        gen = get_readonly_db(db_session)
        db = next(gen)
        assert db.scalar(text("PRAGMA query_only")) == 1
        db.add(Account(name="Взлом", type="cash", currency="RUB", initial_balance_minor=0, is_active=True))
        with pytest.raises(ReadOnlySessionError):
            db.flush()
        db.rollback()
        with pytest.raises(OperationalError, match="readonly"):
            db.execute(text("insert into notifications (type, severity, title, message, dedup_key, created_at, updated_at) values ('system','info','x','x','x', '2026-01-01', '2026-01-01')"))
        db.rollback()
        gen.close()  # выполняет finally: режим чтения снимается
        assert db_session.scalar(text("PRAGMA query_only")) == 0
        assert db_session.scalar(select(func.count(Account.id))) == 0
        db_session.add(Account(name="Обычная запись", type="cash", currency="RUB", initial_balance_minor=0, is_active=True))
        db_session.commit()
        assert db_session.scalar(select(func.count(Account.id))) == 1

    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    def test_only_get_is_allowed(self, seeded_client, method):
        assert getattr(seeded_client, method)("/api/v1/context").status_code == 405


@pytest.fixture()
def file_client(tmp_path) -> Generator[tuple[TestClient, Path, sessionmaker], None, None]:
    db_file = tmp_path / "context-readonly.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    # Тот же обработчик соединения, что у основного движка: WAL и прочие PRAGMA.
    event.listen(engine, "connect", session_module._configure_sqlite)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as s:
        ensure_default_categories(s)

    def per_request_db() -> Generator[Session, None, None]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = per_request_db
    try:
        yield TestClient(app), db_file, factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def file_fingerprint(db_file: Path) -> str:
    """Отпечаток данных: сам файл и WAL (shm — служебный индекс, не данные)."""
    h = hashlib.sha256(db_file.read_bytes())
    wal = db_file.with_name(db_file.name + "-wal")
    if wal.exists():
        h.update(wal.read_bytes())
    return h.hexdigest()


class TestFileDatabaseLikeProduction:
    def test_journal_mode_is_wal(self, file_client):
        _, _, factory = file_client
        with factory() as s:
            assert s.scalar(text("PRAGMA journal_mode")) == "wal"

    def test_context_does_not_change_the_file_and_writes_work_after(self, file_client):
        client, db_file, factory = file_client
        populate(client)
        before = file_fingerprint(db_file)
        for _ in range(3):
            assert client.get("/api/v1/context").status_code == 200
        assert file_fingerprint(db_file) == before
        with factory() as s:
            assert s.scalar(select(func.count(Notification.id))) == 0
            # соединения из пула не остались в режиме только чтения
            assert s.scalar(text("PRAGMA query_only")) == 0
        r = client.post("/api/v1/accounts", json={"name": "Новый", "type": "cash", "currency": "RUB", "initial_balance_minor": 5})
        assert r.status_code == 201
        assert file_fingerprint(db_file) != before
        assert client.get("/api/v1/context").json()["accounts"]["items"][-1]["label"] == "Новый"


class TestArchitecture:
    FORBIDDEN = [
        # методы записи у сессии (у множеств .add() — это не запись в БД)
        r"\bdb\.(add|add_all|delete|commit|flush|merge|bulk_\w+)\(",
        r"\binsert\(", r"\bupdate\(", r"\bdelete\(",
        r"generate_notifications", r"create_system_notification", r"process_recurring_transactions",
        r"exec_driver_sql",
    ]

    def sources(self):
        files = sorted((APP_DIR / "context").glob("*.py")) + [APP_DIR / "api" / "v1" / "context.py"]
        assert len(files) >= 4
        return {f.name: f.read_text(encoding="utf-8") for f in files}

    def test_context_package_has_no_write_operations(self):
        offenders = [
            f"{name}: {pattern}"
            for name, code in self.sources().items()
            for pattern in self.FORBIDDEN
            if re.search(pattern, code)
        ]
        assert offenders == []

    def test_endpoint_uses_readonly_session(self):
        code = self.sources()["context.py"]
        assert "Depends(get_readonly_db)" in code
        assert "Depends(get_db)" not in code

    @pytest.mark.parametrize("module", ["app.context.builder", "app.api.v1.context", "app.context.indicators"])
    def test_module_imports_first_without_cycle(self, module):
        # В свежем интерпретаторе: модуль контекста загружается раньше app.main.
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            cwd=APP_DIR.parent,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
