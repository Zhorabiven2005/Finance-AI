"""Регрессия: расходы одной категории в двух валютах за текущий месяц
роняли весь Dashboard (суммирование RUB + USD). Основные расходы считаются
в базовой валюте — как капитал и аналитика; валюты не смешиваются."""

from __future__ import annotations

from datetime import datetime, timezone


def test_dashboard_with_same_category_expenses_in_two_currencies(seeded_client):
    client = seeded_client
    food = next(c for c in client.get("/api/v1/categories").json() if c["name"] == "Продукты")
    rub = client.post("/api/v1/accounts", json={"name": "Р", "type": "bank", "currency": "RUB", "initial_balance_minor": 0}).json()
    usd = client.post("/api/v1/accounts", json={"name": "Д", "type": "bank", "currency": "USD", "initial_balance_minor": 0}).json()
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for acc, amount in ((rub, 50_000), (usd, 1_299)):
        client.post(
            "/api/v1/transactions",
            json={"account_id": acc["id"], "category_id": food["id"], "type": "expense", "amount_minor": amount, "occurred_at": now},
        )

    r = client.get("/api/v1/dashboard")
    assert r.status_code == 200, r.text
    top = r.json()["top_expenses"]
    assert [(t["category_name"], t["amount"]) for t in top] == [("Продукты", {"minor": 50_000, "currency": "RUB"})]
