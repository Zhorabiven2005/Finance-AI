"""Версионированная схема финансового контекста (Stage 2F).

Снимок docs/financial-context.schema.json должен совпадать со схемой в коде:
любое изменение структуры ответа требует осознанного обновления снимка,
документации и, при несовместимом изменении, номера версии.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

from app import clock
from app.schemas.context import FINANCIAL_CONTEXT_VERSION, FinancialContextOut

SNAPSHOT = Path(__file__).resolve().parents[2] / "docs" / "financial-context.schema.json"


@pytest.fixture(autouse=True)
def fixed_dates(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: date(2026, 10, 17))
    monkeypatch.setattr(clock, "utc_today", lambda: date(2026, 10, 17))


def test_version_format():
    assert re.fullmatch(r"\d+\.\d+", FINANCIAL_CONTEXT_VERSION)
    assert FINANCIAL_CONTEXT_VERSION == "1.0"


def test_snapshot_matches_code():
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert snapshot["schema_version"] == FINANCIAL_CONTEXT_VERSION
    assert snapshot["json_schema"] == FinancialContextOut.model_json_schema(), (
        "Структура контекста изменилась: обновите docs/financial-context.schema.json, "
        "docs/financial-context.md и при несовместимом изменении — версию."
    )


def test_schema_endpoint(seeded_client):
    r = seeded_client.get("/api/v1/context/schema")
    assert r.status_code == 200
    body = r.json()
    assert body["schema_version"] == "1.0"
    assert body["json_schema"] == FinancialContextOut.model_json_schema()


def test_schema_is_strict():
    schema = FinancialContextOut.model_json_schema()
    assert schema["additionalProperties"] is False
    for name, definition in schema["$defs"].items():
        if definition.get("type") == "object" and name != "MoneyOut":
            assert definition.get("additionalProperties") is False, name


def test_response_validates_against_model(seeded_client):
    seeded_client.post("/api/v1/accounts", json={"name": "Карта", "type": "bank", "currency": "RUB", "initial_balance_minor": 1})
    data = seeded_client.get("/api/v1/context").json()
    FinancialContextOut.model_validate(data)
    assert data["meta"]["schema_version"] == FINANCIAL_CONTEXT_VERSION
