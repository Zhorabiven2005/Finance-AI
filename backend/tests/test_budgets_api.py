"""API-тесты бюджетов."""

from __future__ import annotations

import pytest


@pytest.fixture()
def setup(seeded_client):
    client = seeded_client
    account = client.post(
        "/api/v1/accounts",
        json={"name": "Карта", "type": "bank", "currency": "RUB", "initial_balance_minor": 0},
    ).json()
    categories = client.get("/api/v1/categories").json()
    food = next(c for c in categories if c["name"] == "Продукты")
    transport = next(c for c in categories if c["name"] == "Транспорт")
    salary = next(c for c in categories if c["name"] == "Зарплата")
    return {"client": client, "account": account, "food": food, "transport": transport, "salary": salary}


def create_budget(client, category_id, **overrides):
    payload = {
        "category_id": category_id,
        "amount_minor": 3_000_000,
        "currency": "RUB",
        "year": 2026,
        "month": 9,
        **overrides,
    }
    r = client.post("/api/v1/budgets", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def add_expense(client, account_id, category_id, amount_minor, occurred_at):
    r = client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "category_id": category_id,
            "type": "expense",
            "amount_minor": amount_minor,
            "occurred_at": occurred_at,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestCreateBudget:
    def test_create_budget(self, setup):
        budget = create_budget(setup["client"], setup["food"]["id"])
        assert budget["category_name"] == "Продукты"
        assert budget["amount"] == {"minor": 3_000_000, "currency": "RUB"}
        assert budget["spent"]["minor"] == 0
        assert budget["remaining"]["minor"] == 3_000_000
        assert budget["usage_percent"] == 0
        assert budget["status"] == "ok"

    def test_duplicate_budget_rejected(self, setup):
        create_budget(setup["client"], setup["food"]["id"])
        r = setup["client"].post(
            "/api/v1/budgets",
            json={
                "category_id": setup["food"]["id"],
                "amount_minor": 1_000_000,
                "currency": "RUB",
                "year": 2026,
                "month": 9,
            },
        )
        assert r.status_code == 400

    def test_same_category_different_month_allowed(self, setup):
        create_budget(setup["client"], setup["food"]["id"], month=9)
        r = setup["client"].post(
            "/api/v1/budgets",
            json={
                "category_id": setup["food"]["id"],
                "amount_minor": 1_000_000,
                "currency": "RUB",
                "year": 2026,
                "month": 10,
            },
        )
        assert r.status_code == 201

    def test_income_category_rejected(self, setup):
        r = setup["client"].post(
            "/api/v1/budgets",
            json={
                "category_id": setup["salary"]["id"],
                "amount_minor": 1_000_000,
                "currency": "RUB",
                "year": 2026,
                "month": 9,
            },
        )
        assert r.status_code == 400

    def test_unknown_category_404(self, setup):
        r = setup["client"].post(
            "/api/v1/budgets",
            json={"category_id": 999999, "amount_minor": 1000, "currency": "RUB", "year": 2026, "month": 9},
        )
        assert r.status_code == 404

    def test_zero_amount_rejected(self, setup):
        r = setup["client"].post(
            "/api/v1/budgets",
            json={
                "category_id": setup["food"]["id"],
                "amount_minor": 0,
                "currency": "RUB",
                "year": 2026,
                "month": 9,
            },
        )
        assert r.status_code == 422

    def test_invalid_month_rejected(self, setup):
        r = setup["client"].post(
            "/api/v1/budgets",
            json={
                "category_id": setup["food"]["id"],
                "amount_minor": 1000,
                "currency": "RUB",
                "year": 2026,
                "month": 13,
            },
        )
        assert r.status_code == 422

    def test_float_amount_rejected(self, setup):
        r = setup["client"].post(
            "/api/v1/budgets",
            json={
                "category_id": setup["food"]["id"],
                "amount_minor": 100.5,
                "currency": "RUB",
                "year": 2026,
                "month": 9,
            },
        )
        assert r.status_code == 422


class TestBudgetUsageCalculation:
    def test_spending_under_budget(self, setup):
        budget = create_budget(setup["client"], setup["food"]["id"], amount_minor=3_000_000)
        add_expense(setup["client"], setup["account"]["id"], setup["food"]["id"], 2_400_000, "2026-09-10T10:00:00Z")
        updated = setup["client"].get(f"/api/v1/budgets/{budget['id']}").json()
        assert updated["spent"]["minor"] == 2_400_000
        assert updated["remaining"]["minor"] == 600_000
        assert updated["usage_percent"] == 80.0
        assert updated["status"] == "warning"

    def test_spending_exceeds_budget(self, setup):
        budget = create_budget(setup["client"], setup["food"]["id"], amount_minor=3_000_000)
        add_expense(setup["client"], setup["account"]["id"], setup["food"]["id"], 3_400_000, "2026-09-10T10:00:00Z")
        updated = setup["client"].get(f"/api/v1/budgets/{budget['id']}").json()
        assert updated["remaining"]["minor"] == -400_000
        assert updated["usage_percent"] == pytest.approx(113.3)
        assert updated["status"] == "exceeded"

    def test_multiple_expenses_sum_correctly(self, setup):
        budget = create_budget(setup["client"], setup["food"]["id"], amount_minor=1_000_000)
        for amount in (100_000, 200_000, 300_000):
            add_expense(setup["client"], setup["account"]["id"], setup["food"]["id"], amount, "2026-09-10T10:00:00Z")
        updated = setup["client"].get(f"/api/v1/budgets/{budget['id']}").json()
        assert updated["spent"]["minor"] == 600_000

    def test_expenses_outside_month_not_counted(self, setup):
        budget = create_budget(setup["client"], setup["food"]["id"])
        add_expense(setup["client"], setup["account"]["id"], setup["food"]["id"], 100_000, "2026-08-31T23:59:59Z")
        add_expense(setup["client"], setup["account"]["id"], setup["food"]["id"], 200_000, "2026-10-01T00:00:00Z")
        updated = setup["client"].get(f"/api/v1/budgets/{budget['id']}").json()
        assert updated["spent"]["minor"] == 0

    def test_month_boundary_inclusive(self, setup):
        budget = create_budget(setup["client"], setup["food"]["id"])
        add_expense(setup["client"], setup["account"]["id"], setup["food"]["id"], 111, "2026-09-01T00:00:00Z")
        add_expense(setup["client"], setup["account"]["id"], setup["food"]["id"], 222, "2026-09-30T23:59:59Z")
        updated = setup["client"].get(f"/api/v1/budgets/{budget['id']}").json()
        assert updated["spent"]["minor"] == 333

    def test_income_transactions_not_counted_as_spent(self, setup):
        # Категория дохода отдельная, но проверим и что expense-фильтр по
        # типу операции, а не только по категории, действительно применяется.
        budget = create_budget(setup["client"], setup["food"]["id"])
        client = setup["client"]
        client.post(
            "/api/v1/transactions",
            json={
                "account_id": setup["account"]["id"],
                "category_id": setup["salary"]["id"],
                "type": "income",
                "amount_minor": 5_000_000,
                "occurred_at": "2026-09-10T10:00:00Z",
            },
        )
        updated = client.get(f"/api/v1/budgets/{budget['id']}").json()
        assert updated["spent"]["minor"] == 0

    def test_other_category_expenses_not_counted(self, setup):
        budget = create_budget(setup["client"], setup["food"]["id"])
        add_expense(setup["client"], setup["account"]["id"], setup["transport"]["id"], 500_000, "2026-09-10T10:00:00Z")
        updated = setup["client"].get(f"/api/v1/budgets/{budget['id']}").json()
        assert updated["spent"]["minor"] == 0

    def test_deleting_transaction_recomputes_spent(self, setup):
        budget = create_budget(setup["client"], setup["food"]["id"])
        tx = add_expense(setup["client"], setup["account"]["id"], setup["food"]["id"], 500_000, "2026-09-10T10:00:00Z")
        assert setup["client"].get(f"/api/v1/budgets/{budget['id']}").json()["spent"]["minor"] == 500_000
        setup["client"].delete(f"/api/v1/transactions/{tx['id']}")
        assert setup["client"].get(f"/api/v1/budgets/{budget['id']}").json()["spent"]["minor"] == 0


class TestBudgetCurrencyIsolation:
    def test_different_currency_expenses_not_mixed(self, setup):
        client = setup["client"]
        usd_account = client.post(
            "/api/v1/accounts",
            json={"name": "USD", "type": "bank", "currency": "USD", "initial_balance_minor": 0},
        ).json()
        budget = create_budget(client, setup["food"]["id"], currency="RUB")
        add_expense(client, usd_account["id"], setup["food"]["id"], 100_000, "2026-09-10T10:00:00Z")
        updated = client.get(f"/api/v1/budgets/{budget['id']}").json()
        assert updated["spent"]["minor"] == 0

    def test_same_category_different_currency_budgets_independent(self, setup):
        client = setup["client"]
        rub_budget = create_budget(client, setup["food"]["id"], currency="RUB", amount_minor=3_000_000)
        usd_budget_resp = client.post(
            "/api/v1/budgets",
            json={
                "category_id": setup["food"]["id"],
                "amount_minor": 100_000,
                "currency": "USD",
                "year": 2026,
                "month": 9,
            },
        )
        assert usd_budget_resp.status_code == 201


class TestUpdateAndDeleteBudget:
    def test_update_amount(self, setup):
        budget = create_budget(setup["client"], setup["food"]["id"], amount_minor=1_000_000)
        r = setup["client"].patch(f"/api/v1/budgets/{budget['id']}", json={"amount_minor": 2_000_000})
        assert r.status_code == 200
        assert r.json()["amount"]["minor"] == 2_000_000

    def test_delete_budget(self, setup):
        budget = create_budget(setup["client"], setup["food"]["id"])
        r = setup["client"].delete(f"/api/v1/budgets/{budget['id']}")
        assert r.status_code == 204
        assert setup["client"].get(f"/api/v1/budgets/{budget['id']}").status_code == 404


class TestListBudgets:
    def test_filter_by_year_and_month(self, setup):
        client = setup["client"]
        create_budget(client, setup["food"]["id"], month=9)
        create_budget(client, setup["transport"]["id"], month=10)
        r = client.get("/api/v1/budgets", params={"year": 2026, "month": 9})
        assert len(r.json()) == 1
        assert r.json()[0]["category_name"] == "Продукты"

    def test_empty_period_returns_empty_list(self, setup):
        r = setup["client"].get("/api/v1/budgets", params={"year": 2030, "month": 1})
        assert r.json() == []


class TestCategoryDeletionGuard:
    def test_cannot_delete_category_with_budget(self, setup):
        # "Продукты" — базовая категория и уже блокируется по этой причине;
        # чтобы проверить именно защиту от удаления из-за бюджета (а не
        # попасть на is_default), создаём свою категорию.
        client = setup["client"]
        custom = client.post(
            "/api/v1/categories", json={"name": "Хобби", "type": "expense"}
        ).json()
        create_budget(client, custom["id"])
        r = client.delete(f"/api/v1/categories/{custom['id']}")
        assert r.status_code == 400
