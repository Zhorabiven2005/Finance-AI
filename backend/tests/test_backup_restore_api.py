"""JSON-backup: восстановление (Replace) — успех, связи, атомарность, откат."""

from __future__ import annotations

import copy

import pytest

from app.backup import restore as restore_module
from tests.data_helpers import comparable, export_backup, populate, restore_backup


@pytest.fixture()
def snapshot(seeded_client):
    s = populate(seeded_client)
    return s, export_backup(seeded_client)


def wipe(client):
    """Удаляет пользовательские данные через API (как это сделал бы человек)."""
    for g in client.get("/api/v1/goals").json():
        client.delete(f"/api/v1/goals/{g['id']}")
    for r in client.get("/api/v1/recurring-transactions").json():
        client.delete(f"/api/v1/recurring-transactions/{r['id']}")
    for b in client.get("/api/v1/budgets").json():
        client.delete(f"/api/v1/budgets/{b['id']}")
    for d in client.get("/api/v1/debts").json():
        client.delete(f"/api/v1/debts/{d['id']}")
    for t in client.get("/api/v1/transfers").json():
        client.delete(f"/api/v1/transfers/{t['id']}")
    for t in client.get("/api/v1/transactions", params={"limit": 100}).json():
        client.delete(f"/api/v1/transactions/{t['id']}")
    for a in client.get("/api/v1/accounts").json():
        assert client.delete(f"/api/v1/accounts/{a['id']}").status_code == 204


def test_restore_requires_confirmation(seeded_client, snapshot):
    _, doc = snapshot
    before = comparable(export_backup(seeded_client))
    r = restore_backup(seeded_client, doc, confirm=False)
    assert r.status_code == 400
    assert comparable(export_backup(seeded_client)) == before


def test_successful_restore_recreates_everything(seeded_client, snapshot):
    s, doc = snapshot
    wipe(seeded_client)
    assert seeded_client.get("/api/v1/accounts").json() == []

    r = restore_backup(seeded_client, doc)
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["transactions"] == 5

    assert comparable(export_backup(seeded_client)) == comparable(doc)


def test_relationships_and_computed_values_restored(seeded_client, snapshot):
    s, doc = snapshot
    balances = {a["id"]: a["balance"] for a in seeded_client.get("/api/v1/accounts").json()}
    debt = seeded_client.get(f"/api/v1/debts/{s['debt']['id']}").json()
    goal = seeded_client.get(f"/api/v1/goals/{s['goal']['id']}").json()
    wipe(seeded_client)
    restore_backup(seeded_client, doc)

    assert {a["id"]: a["balance"] for a in seeded_client.get("/api/v1/accounts").json()} == balances
    assert seeded_client.get(f"/api/v1/debts/{s['debt']['id']}").json() == debt
    assert seeded_client.get(f"/api/v1/goals/{s['goal']['id']}").json() == goal
    payments = seeded_client.get(f"/api/v1/debts/{s['debt']['id']}/payments").json()
    linked = [p for p in payments if p["transaction_id"]]
    assert len(linked) == 1
    op = seeded_client.get(f"/api/v1/transactions/{linked[0]['transaction_id']}").json()
    assert op["debt_name"] == "Банк"
    cafe = seeded_client.get(f"/api/v1/categories/{s['cafe']['id']}").json()
    assert cafe["parent_id"] == s["food"]["id"] and cafe["icon"] == "coffee"
    # Запуск регулярной операции восстановлен: повторная обработка за ту же
    # дату не создаёт дубль.
    count = len(seeded_client.get("/api/v1/transactions", params={"limit": 100}).json())
    seeded_client.post("/api/v1/recurring-transactions/process", params={"as_of": "2026-09-10"})
    assert len(seeded_client.get("/api/v1/transactions", params={"limit": 100}).json()) == count


def test_restore_replaces_current_data(seeded_client, snapshot):
    _, doc = snapshot
    seeded_client.post(
        "/api/v1/accounts",
        json={"name": "Новый после бэкапа", "type": "cash", "currency": "RUB", "initial_balance_minor": 1},
    )
    restore_backup(seeded_client, doc)
    names = [a["name"] for a in seeded_client.get("/api/v1/accounts").json()]
    assert "Новый после бэкапа" not in names
    assert comparable(export_backup(seeded_client)) == comparable(doc)


def test_repeated_restore_is_stable(seeded_client, snapshot):
    _, doc = snapshot
    restore_backup(seeded_client, doc)
    first = comparable(export_backup(seeded_client))
    restore_backup(seeded_client, doc)
    assert comparable(export_backup(seeded_client)) == first == comparable(doc)


def test_restore_into_empty_database(client, seeded_client, snapshot):
    # seeded_client и client делят одну in-memory БД; здесь важно, что
    # restore сам создаёт строку настроек, если её нет.
    _, doc = snapshot
    wipe(seeded_client)
    doc2 = copy.deepcopy(doc)
    doc2["settings"]["locale"] = "en-US"
    assert restore_backup(client, doc2).status_code == 200
    assert export_backup(client)["settings"]["locale"] == "en-US"


def test_invalid_backup_leaves_database_untouched(seeded_client, snapshot):
    _, doc = snapshot
    seeded_client.post(
        "/api/v1/accounts",
        json={"name": "Текущий", "type": "cash", "currency": "RUB", "initial_balance_minor": 1},
    )
    before = comparable(export_backup(seeded_client))
    bad = copy.deepcopy(doc)
    bad["data"]["goal_entries"][0]["goal_id"] = 999_999
    r = restore_backup(seeded_client, bad)
    assert r.status_code == 400
    assert "данные не изменены" in r.json()["detail"]
    assert comparable(export_backup(seeded_client)) == before


def test_failure_midway_rolls_back_everything(seeded_client, snapshot, monkeypatch):
    """Сбой ПОСЛЕ удаления старых данных и вставки части новых — например,
    диск заполнился на последней таблице. БД должна остаться прежней."""
    _, doc = snapshot
    seeded_client.post(
        "/api/v1/accounts",
        json={"name": "Должен выжить", "type": "cash", "currency": "RUB", "initial_balance_minor": 1},
    )
    before = comparable(export_backup(seeded_client))

    original = restore_module._insert_rows

    def failing(db, section, rows):
        if section == "goal_entries":
            raise RuntimeError("disk full")
        original(db, section, rows)

    monkeypatch.setattr(restore_module, "_insert_rows", failing)
    r = restore_backup(seeded_client, doc)
    assert r.status_code == 500
    assert "не изменены" in r.json()["detail"]
    monkeypatch.undo()

    after = comparable(export_backup(seeded_client))
    assert after == before
    assert any(a["name"] == "Должен выжить" for a in seeded_client.get("/api/v1/accounts").json())


def test_backup_from_one_currency_settings_restored(seeded_client, snapshot):
    _, doc = snapshot
    restore_backup(seeded_client, doc)
    assert seeded_client.get("/api/v1/settings").json()["base_currency"] == doc["base_currency"]
