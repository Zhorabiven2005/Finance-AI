"""Backup version 2 (уведомления) и обратная совместимость с version 1."""

from __future__ import annotations

import copy
from datetime import date

import pytest

from app import clock
from app.backup.format import BACKUP_FORMAT_VERSION
from tests.data_helpers import comparable, export_backup, populate, preview_backup, restore_backup


@pytest.fixture()
def client(seeded_client, monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: date(2026, 10, 15))
    return seeded_client


@pytest.fixture()
def with_notifications(client):
    populate(client)
    client.post(
        "/api/v1/debts",
        json={"counterparty_name": "Срочно", "direction": "i_owe", "principal_minor": 100_000, "currency": "RUB", "due_date": "2026-10-10"},
    )
    client.post(
        "/api/v1/debts",
        json={"counterparty_name": "Сегодня", "direction": "owed_to_me", "principal_minor": 5_000, "currency": "USD", "due_date": "2026-10-15"},
    )
    client.post("/api/v1/notifications/check")
    items = client.get("/api/v1/notifications").json()
    client.post(f"/api/v1/notifications/{items[0]['id']}/read")
    client.delete(f"/api/v1/notifications/{items[1]['id']}")
    return export_backup(client)


def as_v1(doc):
    v1 = copy.deepcopy(doc)
    v1["version"] = 1
    v1["data"].pop("notifications")
    for t in v1["data"]["transactions"]:  # полей назначения (version 3) в v1 не было
        for key in ("purpose", "purpose_account_id", "purpose_debt_id"):
            t.pop(key, None)
    return v1


def test_export_is_version_2_with_notifications(with_notifications):
    doc = with_notifications
    assert doc["version"] == BACKUP_FORMAT_VERSION == 3  # version 3 (Stage 3F) сохраняет уведомления
    notes = doc["data"]["notifications"]
    # Два долга со сроками + регулярная операция из populate(), чья дата
    # (10.10) уже прошла и она не проведена.
    assert sorted(x["type"] for x in notes) == ["debt_due", "debt_overdue", "recurring_transaction_missed"]
    n = notes[0]
    assert set(n) >= {"type", "severity", "title", "message", "entity_type", "entity_id", "dedup_key", "data", "read_at", "resolved_at", "deleted_at"}
    assert sum(1 for x in notes if x["read_at"]) == 2  # прочитанное + удалённое
    assert sum(1 for x in notes if x["deleted_at"]) == 1


def test_restore_v2_preserves_notifications_states_and_due_dates(client, with_notifications):
    doc = with_notifications
    client.delete(f"/api/v1/debts/{next(d['id'] for d in doc['data']['debts'] if d['counterparty_name'] == 'Срочно')}")
    r = restore_backup(client, doc)
    assert r.status_code == 200, r.text
    assert comparable(export_backup(client)) == comparable(doc)
    debts = {d["counterparty_name"]: d for d in client.get("/api/v1/debts").json()}
    assert (debts["Срочно"]["due_date"], debts["Срочно"]["due_state"]) == ("2026-10-10", "overdue")
    assert debts["Сегодня"]["due_state"] == "today"
    # Удалённое пользователем не вернулось ни после restore, ни после проверки.
    client.post("/api/v1/notifications/check")
    visible = client.get("/api/v1/notifications").json()
    assert sum(1 for n in visible if n["type"] != "system") == 2


def test_restore_records_system_notification(client, with_notifications):
    restore_backup(client, with_notifications)
    systems = [n for n in client.get("/api/v1/notifications").json() if n["type"] == "system"]
    assert len(systems) == 1
    assert systems[0]["title"] == "Данные восстановлены из резервной копии"


def test_v1_backup_still_restores(client, with_notifications):
    v1 = as_v1(with_notifications)
    preview = preview_backup(client, v1).json()
    assert preview["valid"] is True and preview["version"] == 1
    assert preview["counts"]["notifications"] == 0

    r = restore_backup(client, v1)
    assert r.status_code == 200, r.text
    restored = export_backup(client)
    assert restored["version"] == BACKUP_FORMAT_VERSION
    expected = comparable(with_notifications)
    expected["data"]["notifications"] = []
    assert comparable(restored) == expected
    # Уведомления заново создаёт обычная проверка.
    assert client.post("/api/v1/notifications/check").json()["created"] == 3


def test_v1_document_with_notifications_section_is_rejected(client, with_notifications):
    v1 = as_v1(with_notifications)
    v1["data"]["notifications"] = []
    errors = preview_backup(client, v1).json()["errors"]
    assert any("notifications" in e and "неизвестное поле" in e for e in errors)


def test_v2_document_without_notifications_section_is_rejected(client, with_notifications):
    doc = copy.deepcopy(with_notifications)
    doc["data"].pop("notifications")
    errors = preview_backup(client, doc).json()["errors"]
    assert any("notifications" in e for e in errors)


@pytest.mark.parametrize("version", [4, 99])
def test_unknown_version_rejected(client, with_notifications, version):
    doc = dict(with_notifications, version=version)
    errors = preview_backup(client, doc).json()["errors"]
    assert "версия резервной копии не поддерживается" in errors[0]


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("type", "push_spam", "type"),
        ("severity", "critical", "severity"),
        ("data", "[1, 2]", "JSON-объектом"),
        ("data", "{not json", "JSON-объектом"),
        ("read_at", "2026-10-01T10:00:00", "read_at"),
    ],
)
def test_invalid_notification_rejected(client, with_notifications, field, value, message):
    doc = copy.deepcopy(with_notifications)
    doc["data"]["notifications"][0][field] = value
    errors = preview_backup(client, doc).json()["errors"]
    assert any(message in e for e in errors), errors


def test_duplicate_dedup_key_rejected(client, with_notifications):
    doc = copy.deepcopy(with_notifications)
    doc["data"]["notifications"][1]["dedup_key"] = doc["data"]["notifications"][0]["dedup_key"]
    assert any("повторяется" in e for e in preview_backup(client, doc).json()["errors"])


def test_dangling_entity_link_is_allowed(client, with_notifications):
    doc = copy.deepcopy(with_notifications)
    doc["data"]["notifications"][0]["entity_id"] = 999_999
    assert preview_backup(client, doc).json()["valid"] is True
