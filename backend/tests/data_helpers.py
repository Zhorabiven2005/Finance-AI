"""Общие хелперы тестов импорта/экспорта: наполняют БД всеми видами
сущностей через API, чтобы данные соблюдали те же инварианты, что и в жизни."""

from __future__ import annotations

import base64
import json


def _ok(r, status=201):
    assert r.status_code == status, r.text
    return r.json()


def populate(client) -> dict:
    """Заполняет БД: счета (RUB, USD), подкатегория, операции, перевод, долг
    с платежом со счётом и без, бюджет, регулярная операция с запуском,
    цель с записями."""
    cats = client.get("/api/v1/categories").json()
    food = next(c for c in cats if c["name"] == "Продукты")
    salary = next(c for c in cats if c["name"] == "Зарплата")

    sber = _ok(client.post("/api/v1/accounts", json={"name": "Сбер", "type": "bank", "currency": "RUB", "initial_balance_minor": 10_000_000}))
    cash = _ok(client.post("/api/v1/accounts", json={"name": "Наличные", "type": "cash", "currency": "RUB", "initial_balance_minor": 500_000}))
    usd = _ok(client.post("/api/v1/accounts", json={"name": "Доллары", "type": "bank", "currency": "USD", "initial_balance_minor": 100_000}))

    cafe = _ok(client.post("/api/v1/categories", json={"name": "Кафе", "type": "expense", "icon": "coffee", "parent_id": food["id"]}))

    t1 = _ok(client.post("/api/v1/transactions", json={"account_id": sber["id"], "category_id": salary["id"], "type": "income", "amount_minor": 15_000_000, "occurred_at": "2026-09-01T09:00:00Z", "comment": "Сентябрь"}))
    t2 = _ok(client.post("/api/v1/transactions", json={"account_id": sber["id"], "category_id": cafe["id"], "type": "expense", "amount_minor": 45_050, "occurred_at": "2026-09-02T12:30:00Z", "comment": "Кофе, «круассан»; чек №1"}))
    t3 = _ok(client.post("/api/v1/transactions", json={"account_id": usd["id"], "category_id": food["id"], "type": "expense", "amount_minor": 1_299, "occurred_at": "2026-09-03T18:00:00Z"}))

    transfer = _ok(client.post("/api/v1/transfers", json={"from_account_id": sber["id"], "to_account_id": cash["id"], "amount_minor": 200_000, "occurred_at": "2026-09-04T10:00:00Z", "comment": "Снятие"}))

    debt = _ok(client.post("/api/v1/debts", json={"counterparty_name": "Банк", "direction": "i_owe", "principal_minor": 3_000_000, "currency": "RUB", "due_date": "2026-12-31"}))
    p1 = _ok(client.post(f"/api/v1/debts/{debt['id']}/payments", json={"amount_minor": 1_000_000, "paid_at": "2026-09-05T10:00:00Z", "account_id": sber["id"]}))
    p2 = _ok(client.post(f"/api/v1/debts/{debt['id']}/payments", json={"amount_minor": 250_000, "paid_at": "2026-09-06T10:00:00Z"}))

    budget = _ok(client.post("/api/v1/budgets", json={"category_id": food["id"], "amount_minor": 3_000_000, "currency": "RUB", "year": 2026, "month": 9}))

    rule = _ok(client.post("/api/v1/recurring-transactions", json={"type": "expense", "account_id": sber["id"], "category_id": food["id"], "amount_minor": 100_000, "start_date": "2026-09-10", "frequency": "monthly"}))
    _ok(client.post("/api/v1/recurring-transactions/process", params={"as_of": "2026-09-10"}), 200)

    goal = _ok(client.post("/api/v1/goals", json={"name": "MacBook", "target_amount_minor": 18_000_000, "currency": "RUB", "target_date": "2027-03-01"}))
    _ok(client.post(f"/api/v1/goals/{goal['id']}/entries", json={"type": "contribution", "amount_minor": 7_200_000, "occurred_at": "2026-09-07T10:00:00Z"}))
    _ok(client.post(f"/api/v1/goals/{goal['id']}/entries", json={"type": "withdrawal", "amount_minor": 200_000, "occurred_at": "2026-09-08T10:00:00Z", "comment": "Нужно было"}))

    return {
        "sber": sber, "cash": cash, "usd": usd, "food": food, "salary": salary, "cafe": cafe,
        "transactions": [t1, t2, t3], "transfer": transfer, "debt": debt, "payments": [p1, p2],
        "budget": budget, "rule": rule, "goal": goal,
    }


def export_backup(client) -> dict:
    r = client.get("/api/v1/export/backup")
    assert r.status_code == 200, r.text
    return r.json()


def comparable(doc: dict) -> dict:
    """Backup без времени экспорта и без системных событий «данные
    восстановлены» (они появляются ПОСЛЕ restore по определению) — для
    сравнения состояний БД."""
    out = {k: v for k, v in doc.items() if k not in ("exported_at", "version")}
    data = dict(out["data"])
    data["notifications"] = [
        n for n in data.get("notifications", []) if not n["dedup_key"].startswith("system:restore:")
    ]
    out["data"] = data
    return out


def raw(doc) -> bytes:
    return doc if isinstance(doc, bytes) else json.dumps(doc, ensure_ascii=False).encode("utf-8")


def preview_backup(client, doc):
    return client.post("/api/v1/import/backup/preview", content=raw(doc), headers={"Content-Type": "application/json"})


def restore_backup(client, doc, confirm=True):
    return client.post(
        "/api/v1/import/backup/restore",
        params={"confirm": "true" if confirm else "false"},
        content=raw(doc),
        headers={"Content-Type": "application/json"},
    )


def b64(text: str | bytes, encoding: str = "utf-8") -> str:
    data = text if isinstance(text, bytes) else text.encode(encoding)
    return base64.b64encode(data).decode("ascii")


def csv_preview(client, csv_text, options=None, encoding="utf-8"):
    return client.post(
        "/api/v1/import/transactions/preview",
        json={"file_base64": b64(csv_text, encoding), "options": options or {}},
    )


def csv_commit(client, csv_text, options=None, confirm=True, encoding="utf-8"):
    return client.post(
        "/api/v1/import/transactions/commit",
        json={"file_base64": b64(csv_text, encoding), "options": options or {}, "confirm": confirm},
    )
