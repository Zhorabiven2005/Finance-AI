"""Контракт «Обработать сейчас». Фронтенд показывает диалог «Новых операций
нет», опираясь на created_transactions == 0; повторный запуск идемпотентен."""

from __future__ import annotations


def setup_rule(client):
    account = client.post(
        "/api/v1/accounts",
        json={"name": "Карта", "type": "bank", "currency": "RUB", "initial_balance_minor": 0},
    ).json()
    rent = next(c for c in client.get("/api/v1/categories").json() if c["name"] == "Жильё")
    r = client.post(
        "/api/v1/recurring-transactions",
        json={
            "type": "expense",
            "account_id": account["id"],
            "category_id": rent["id"],
            "amount_minor": 3_500_000,
            "start_date": "2026-09-01",
            "frequency": "monthly",
        },
    )
    assert r.status_code == 201, r.text


def process(client):
    return client.post("/api/v1/recurring-transactions/process", params={"as_of": "2026-09-01"})


def tx_count(client):
    return len(client.get("/api/v1/transactions").json())


def test_no_rules_returns_zero_not_error(seeded_client):
    r = process(seeded_client)
    assert r.status_code == 200
    assert r.json()["created_transactions"] == 0
    assert tx_count(seeded_client) == 0


def test_second_run_reports_zero_and_adds_no_duplicates(seeded_client):
    setup_rule(seeded_client)
    first = process(seeded_client).json()
    second = process(seeded_client).json()
    third = process(seeded_client).json()
    assert first["created_transactions"] == 1
    assert second["created_transactions"] == 0
    assert third["created_transactions"] == 0
    assert tx_count(seeded_client) == 1
