"""JSON-backup: проверка файла (preview). Preview не меняет БД."""

from __future__ import annotations

import copy
import json

import pytest

from app.api.v1 import data_transfer
from app.backup.format import BACKUP_FORMAT_VERSION
from tests.data_helpers import comparable, export_backup, populate, preview_backup


@pytest.fixture()
def backup(seeded_client):
    populate(seeded_client)
    return export_backup(seeded_client)


def invalid(client, doc) -> list[str]:
    r = preview_backup(client, doc)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] is False, body
    return body["errors"]


def mutate(doc, fn):
    doc = copy.deepcopy(doc)
    fn(doc)
    return doc


def test_valid_backup_preview_returns_summary(seeded_client, backup):
    r = preview_backup(seeded_client, backup)
    body = r.json()
    assert body["valid"] is True
    assert body["version"] == BACKUP_FORMAT_VERSION
    assert body["counts"]["accounts"] == 3
    assert body["counts"]["transactions"] == 5
    assert body["counts"]["goal_entries"] == 2
    assert body["exported_at"] == backup["exported_at"]


def test_preview_does_not_change_database(seeded_client, backup):
    other = mutate(backup, lambda d: d["data"]["accounts"].clear())
    before = comparable(export_backup(seeded_client))
    preview_backup(seeded_client, backup)
    preview_backup(seeded_client, other)
    preview_backup(seeded_client, b"{broken")
    assert comparable(export_backup(seeded_client)) == before


def test_invalid_json(seeded_client):
    errors = invalid(seeded_client, b'{"format": "finance-ai-backup", ')
    assert "не корректный JSON" in errors[0]


def test_empty_file(seeded_client):
    assert "пуст" in invalid(seeded_client, b"   ")[0]


def test_not_utf8(seeded_client):
    assert "UTF-8" in invalid(seeded_client, "{\"format\": \"тест\"}".encode("cp1251"))[0]


@pytest.mark.parametrize("payload", [[1, 2], {"format": "other-app", "version": 1}, {"version": 1}, "строка"])
def test_not_a_finance_ai_backup(seeded_client, payload):
    assert "не является резервной копией Finance AI" in invalid(seeded_client, payload)[0]


@pytest.mark.parametrize("version", [4, 0, "2", None, True])
def test_unsupported_version(seeded_client, backup, version):
    doc = mutate(backup, lambda d: d.__setitem__("version", version))
    assert "версия резервной копии не поддерживается" in invalid(seeded_client, doc)[0]


def test_missing_field(seeded_client, backup):
    doc = mutate(backup, lambda d: d["data"]["accounts"][0].pop("name"))
    errors = invalid(seeded_client, doc)
    assert any("Счета" in e and "name" in e and "обязательное поле" in e for e in errors)


def test_missing_section(seeded_client, backup):
    doc = mutate(backup, lambda d: d["data"].pop("goals"))
    assert any("goals" in e for e in invalid(seeded_client, doc))


def test_unknown_field(seeded_client, backup):
    doc = mutate(backup, lambda d: d["data"]["goals"][0].__setitem__("hacked", 1))
    assert any("неизвестное поле" in e for e in invalid(seeded_client, doc))


@pytest.mark.parametrize("bad", ["100", 100.5, True, None])
def test_invalid_amount_type(seeded_client, backup, bad):
    doc = mutate(backup, lambda d: d["data"]["transactions"][0].__setitem__("amount_minor", bad))
    assert any("amount_minor" in e for e in invalid(seeded_client, doc))


@pytest.mark.parametrize("bad", [0, -100, 10**16])
def test_invalid_money_value(seeded_client, backup, bad):
    doc = mutate(backup, lambda d: d["data"]["transfers"][0].__setitem__("amount_minor", bad))
    assert any("Переводы" in e for e in invalid(seeded_client, doc))


def test_invalid_currency(seeded_client, backup):
    doc = mutate(backup, lambda d: d["data"]["goals"][0].__setitem__("currency", "XXX"))
    assert any("неизвестная валюта «XXX»" in e for e in invalid(seeded_client, doc))


def test_currency_mismatch_with_account(seeded_client, backup):
    def fn(d):
        tx = next(t for t in d["data"]["transactions"] if t["currency"] == "RUB")
        tx["currency"] = "USD"

    assert any("валюта операции не совпадает" in e for e in invalid(seeded_client, fn and mutate(backup, fn)))


@pytest.mark.parametrize(
    "section, field, label",
    [
        ("transactions", "account_id", "счёт id=999999"),
        ("transactions", "category_id", "категория id=999999"),
        ("goal_entries", "goal_id", "цель id=999999"),
        ("debt_payments", "debt_id", "долг id=999999"),
        ("budgets", "category_id", "категория id=999999"),
        ("recurring_transaction_runs", "transaction_id", "операция id=999999"),
    ],
)
def test_broken_foreign_keys(seeded_client, backup, section, field, label):
    doc = mutate(backup, lambda d: d["data"][section][0].__setitem__(field, 999_999))
    assert any(label in e for e in invalid(seeded_client, doc))


def test_duplicate_ids(seeded_client, backup):
    def fn(d):
        d["data"]["accounts"].append(copy.deepcopy(d["data"]["accounts"][0]))

    assert any("встречается 2 раза" in e for e in invalid(seeded_client, mutate(backup, fn)))


def test_duplicate_json_keys(seeded_client, backup):
    text = json.dumps(backup, ensure_ascii=False)
    v = f'"version": {BACKUP_FORMAT_VERSION},'
    text = text.replace(v, v + " " + v, 1)
    assert "повторяющийся ключ" in invalid(seeded_client, text.encode())[0]


def test_category_depth_greater_than_one(seeded_client, backup):
    def fn(d):
        cafe = next(c for c in d["data"]["categories"] if c["name"] == "Кафе")
        d["data"]["categories"].append(
            {**cafe, "id": 900, "name": "Внучка", "icon": None, "parent_id": cafe["id"]}
        )

    assert any("вложенность больше одного уровня" in e for e in invalid(seeded_client, mutate(backup, fn)))


def test_category_cycle(seeded_client, backup):
    def fn(d):
        a, b = d["data"]["categories"][0], d["data"]["categories"][1]
        b["type"] = a["type"]
        a["parent_id"], b["parent_id"] = b["id"], a["id"]

    errors = invalid(seeded_client, mutate(backup, fn))
    assert any("цикл" in e for e in errors)


def test_category_self_parent_and_type_mismatch(seeded_client, backup):
    def fn(d):
        cats = d["data"]["categories"]
        cats[0]["parent_id"] = cats[0]["id"]
        cafe = next(c for c in cats if c["name"] == "Кафе")
        cafe["type"] = "income"

    errors = invalid(seeded_client, mutate(backup, fn))
    assert any("родителем самой себя" in e for e in errors)
    assert any("тип подкатегории" in e for e in errors)


def test_debt_ledger_invariant(seeded_client, backup):
    # Операция от платежа по долгу пропала — платёж со счётом остался без
    # движения денег. Восстанавливать такое нельзя.
    def fn(d):
        d["data"]["transactions"] = [t for t in d["data"]["transactions"] if t["debt_payment_id"] is None]

    assert any("ровно одна связанная операция" in e for e in invalid(seeded_client, mutate(backup, fn)))


def test_goal_with_negative_saved(seeded_client, backup):
    def fn(d):
        d["data"]["goal_entries"][1]["amount_minor"] = 99_999_999

    assert any("списаний больше" in e for e in invalid(seeded_client, mutate(backup, fn)))


@pytest.mark.parametrize("bad", ["2026-13-01T00:00:00Z", "вчера", "2026-09-01T10:00:00", 123])
def test_invalid_datetimes(seeded_client, backup, bad):
    doc = mutate(backup, lambda d: d["data"]["transactions"][0].__setitem__("occurred_at", bad))
    assert any("occurred_at" in e for e in invalid(seeded_client, doc))


def test_invalid_date(seeded_client, backup):
    doc = mutate(backup, lambda d: d["data"]["debts"][0].__setitem__("due_date", "31.12.2026"))
    assert any("due_date" in e for e in invalid(seeded_client, doc))


def test_empty_backup(seeded_client, backup):
    def fn(d):
        for v in d["data"].values():
            v.clear()

    assert any("пуста" in e for e in invalid(seeded_client, mutate(backup, fn)))


def test_too_large_file(seeded_client, backup, monkeypatch):
    monkeypatch.setattr(data_transfer, "MAX_BACKUP_BYTES", 1000)
    r = preview_backup(seeded_client, backup)
    assert r.status_code == 413
    assert "слишком большой" in r.json()["detail"]


def test_errors_mention_record_ids(seeded_client, backup):
    doc = mutate(backup, lambda d: d["data"]["goals"][0].__setitem__("target_amount_minor", -1))
    errors = invalid(seeded_client, doc)
    assert any(f"id={backup['data']['goals'][0]['id']}" in e for e in errors)
