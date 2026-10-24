"""API-тесты доходов и расходов, включая пересчёт баланса счёта."""

from __future__ import annotations

import pytest


@pytest.fixture()
def account(seeded_client):
    r = seeded_client.post(
        "/api/v1/accounts",
        json={"name": "Карта", "type": "bank", "currency": "RUB", "initial_balance_minor": 100_000},
    )
    return r.json()


@pytest.fixture()
def income_category(seeded_client):
    return seeded_client.get("/api/v1/categories", params={"type": "income"}).json()[0]


@pytest.fixture()
def expense_category(seeded_client):
    return seeded_client.get("/api/v1/categories", params={"type": "expense"}).json()[0]


def account_balance(client, account_id: int) -> int:
    return client.get(f"/api/v1/accounts/{account_id}").json()["balance"]["minor"]


class TestIncome:
    def test_income_increases_balance(self, seeded_client, account, income_category):
        r = seeded_client.post(
            "/api/v1/transactions",
            json={
                "account_id": account["id"],
                "category_id": income_category["id"],
                "type": "income",
                "amount_minor": 25_000,
                "occurred_at": "2026-01-10T09:00:00Z",
                "comment": "Зарплата",
            },
        )
        assert r.status_code == 201
        assert account_balance(seeded_client, account["id"]) == 125_000

    def test_income_with_expense_category_rejected(self, seeded_client, account, expense_category):
        r = seeded_client.post(
            "/api/v1/transactions",
            json={
                "account_id": account["id"],
                "category_id": expense_category["id"],
                "type": "income",
                "amount_minor": 1000,
                "occurred_at": "2026-01-10T09:00:00Z",
            },
        )
        assert r.status_code == 400


class TestExpense:
    def test_expense_decreases_balance(self, seeded_client, account, expense_category):
        r = seeded_client.post(
            "/api/v1/transactions",
            json={
                "account_id": account["id"],
                "category_id": expense_category["id"],
                "type": "expense",
                "amount_minor": 15_000,
                "occurred_at": "2026-01-11T09:00:00Z",
            },
        )
        assert r.status_code == 201
        assert account_balance(seeded_client, account["id"]) == 85_000

    def test_expense_can_make_balance_negative(self, seeded_client, account, expense_category):
        seeded_client.post(
            "/api/v1/transactions",
            json={
                "account_id": account["id"],
                "category_id": expense_category["id"],
                "type": "expense",
                "amount_minor": 500_000,
                "occurred_at": "2026-01-11T09:00:00Z",
            },
        )
        assert account_balance(seeded_client, account["id"]) == -400_000


class TestBalanceRecomputation:
    def test_editing_amount_recomputes_balance(self, seeded_client, account, expense_category):
        tx = seeded_client.post(
            "/api/v1/transactions",
            json={
                "account_id": account["id"],
                "category_id": expense_category["id"],
                "type": "expense",
                "amount_minor": 10_000,
                "occurred_at": "2026-01-11T09:00:00Z",
            },
        ).json()
        assert account_balance(seeded_client, account["id"]) == 90_000

        seeded_client.patch(f"/api/v1/transactions/{tx['id']}", json={"amount_minor": 40_000})
        assert account_balance(seeded_client, account["id"]) == 60_000

    def test_deleting_transaction_recomputes_balance(self, seeded_client, account, income_category):
        tx = seeded_client.post(
            "/api/v1/transactions",
            json={
                "account_id": account["id"],
                "category_id": income_category["id"],
                "type": "income",
                "amount_minor": 20_000,
                "occurred_at": "2026-01-11T09:00:00Z",
            },
        ).json()
        assert account_balance(seeded_client, account["id"]) == 120_000

        r = seeded_client.delete(f"/api/v1/transactions/{tx['id']}")
        assert r.status_code == 204
        assert account_balance(seeded_client, account["id"]) == 100_000

    def test_changing_transaction_account_recomputes_both(
        self, seeded_client, account, income_category
    ):
        other = seeded_client.post(
            "/api/v1/accounts",
            json={"name": "Второй счёт", "type": "cash", "currency": "RUB", "initial_balance_minor": 0},
        ).json()
        tx = seeded_client.post(
            "/api/v1/transactions",
            json={
                "account_id": account["id"],
                "category_id": income_category["id"],
                "type": "income",
                "amount_minor": 30_000,
                "occurred_at": "2026-01-11T09:00:00Z",
            },
        ).json()
        assert account_balance(seeded_client, account["id"]) == 130_000
        assert account_balance(seeded_client, other["id"]) == 0

        seeded_client.patch(
            f"/api/v1/transactions/{tx['id']}", json={"account_id": other["id"]}
        )
        assert account_balance(seeded_client, account["id"]) == 100_000
        assert account_balance(seeded_client, other["id"]) == 30_000

    def test_many_small_transactions_no_float_drift(
        self, seeded_client, account, expense_category
    ):
        for _ in range(100):
            seeded_client.post(
                "/api/v1/transactions",
                json={
                    "account_id": account["id"],
                    "category_id": expense_category["id"],
                    "type": "expense",
                    "amount_minor": 1,
                    "occurred_at": "2026-01-11T09:00:00Z",
                },
            )
        # 100 копеек = 1 рубль ровно, без накопленной ошибки округления.
        assert account_balance(seeded_client, account["id"]) == 100_000 - 100


class TestValidation:
    def test_amount_must_be_positive(self, seeded_client, account, expense_category):
        r = seeded_client.post(
            "/api/v1/transactions",
            json={
                "account_id": account["id"],
                "category_id": expense_category["id"],
                "type": "expense",
                "amount_minor": 0,
                "occurred_at": "2026-01-11T09:00:00Z",
            },
        )
        assert r.status_code == 422

    def test_float_amount_rejected(self, seeded_client, account, expense_category):
        r = seeded_client.post(
            "/api/v1/transactions",
            json={
                "account_id": account["id"],
                "category_id": expense_category["id"],
                "type": "expense",
                "amount_minor": 99.99,
                "occurred_at": "2026-01-11T09:00:00Z",
            },
        )
        assert r.status_code == 422

    def test_unknown_account_404(self, seeded_client, expense_category):
        r = seeded_client.post(
            "/api/v1/transactions",
            json={
                "account_id": 9999,
                "category_id": expense_category["id"],
                "type": "expense",
                "amount_minor": 100,
                "occurred_at": "2026-01-11T09:00:00Z",
            },
        )
        assert r.status_code == 404
