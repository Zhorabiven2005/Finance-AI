"""Smoke-тесты API этапа 0.

Раньше модуль создавал собственный TestClient(app) без подмены get_db, и
запросы /health и /settings шли в рабочую backend/data/finance.db. Теперь
они используют общие фикстуры tests/conftest.py — изолированную SQLite в
памяти, как все остальные тесты.
"""

from __future__ import annotations

from pathlib import Path

from app.config import BACKEND_DIR, settings
from app.db.models import AppSettings
from app.db.session import engine

MAIN_DB = (BACKEND_DIR / "data" / "finance.db").resolve()


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["ai_configured"] is False


def test_settings_returns_base_currency(client):
    # В пустой тестовой БД строки настроек нет — значение из конфигурации.
    r = client.get("/api/v1/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["base_currency"] == "RUB"
    assert body["currency"]["exponent"] == 2


def test_settings_read_from_database_row(client, db_session):
    db_session.add(AppSettings(base_currency="RUB", locale="ru-RU"))
    db_session.commit()
    body = client.get("/api/v1/settings").json()
    assert body["base_currency"] == "RUB"
    assert body["locale"] == "ru-RU"


def test_currencies_list(client):
    r = client.get("/api/v1/currencies")
    assert r.status_code == 200
    assert "RUB" in [c["code"] for c in r.json()]


def test_openapi_available(client):
    assert client.get("/openapi.json").status_code == 200


def test_production_engine_never_points_to_main_database():
    """Страж изоляции: рабочий движок в тестах направлен во временный каталог
    (tests/conftest.py), а не в backend/data/finance.db."""
    from tests.conftest import ISOLATED_DB_DIR

    engine_db = Path(engine.url.database).resolve()
    assert settings.db_file.resolve() == engine_db
    assert engine_db != MAIN_DB
    assert Path(ISOLATED_DB_DIR).resolve() in engine_db.parents
