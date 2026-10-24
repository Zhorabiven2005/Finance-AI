"""API-тесты главного финансового экрана."""

from __future__ import annotations

from datetime import datetime, timezone


class TestDashboard:
    def test_empty_state(self, client):
        r = client.get("/api/v1/dashboard")
        assert r.status_code == 200
        body = r.json()
        assert body["net_worth"]["minor"] == 0
        assert body["accounts"] == []
        assert body["debts"]["items"] == []
        assert body["recent_transactions"] == []
        assert body["top_expenses"] == []

    def test_net_worth_sums_accounts(self, client):
        client.post(
            "/api/v1/accounts",
            json={"name": "A", "type": "bank", "currency": "RUB", "initial_balance_minor": 100_000},
        )
        client.post(
            "/api/v1/accounts",
            json={"name": "B", "type": "cash", "currency": "RUB", "initial_balance_minor": 25_000},
        )
        r = client.get("/api/v1/dashboard")
        assert r.json()["net_worth"]["minor"] == 125_000

    def test_net_worth_accounts_for_debts(self, client):
        client.post(
            "/api/v1/accounts",
            json={"name": "A", "type": "bank", "currency": "RUB", "initial_balance_minor": 100_000},
        )
        client.post(
            "/api/v1/debts",
            json={
                "counterparty_name": "Банк",
                "direction": "i_owe",
                "principal_minor": 30_000,
                "currency": "RUB",
            },
        )
        client.post(
            "/api/v1/debts",
            json={
                "counterparty_name": "Друг",
                "direction": "owed_to_me",
                "principal_minor": 10_000,
                "currency": "RUB",
            },
        )
        r = client.get("/api/v1/dashboard")
        body = r.json()
        # 100000 (счета) - 30000 (я должен) + 10000 (мне должны) = 80000
        assert body["net_worth"]["minor"] == 80_000
        assert body["debts"]["i_owe_total"]["minor"] == 30_000
        assert body["debts"]["owed_to_me_total"]["minor"] == 10_000
        assert len(body["debts"]["items"]) == 2

    def test_paid_debt_excluded_from_open_items(self, client):
        debt = client.post(
            "/api/v1/debts",
            json={
                "counterparty_name": "Банк",
                "direction": "i_owe",
                "principal_minor": 5_000,
                "currency": "RUB",
            },
        ).json()
        client.post(
            f"/api/v1/debts/{debt['id']}/payments",
            json={"amount_minor": 5_000, "paid_at": "2026-02-01T12:00:00Z"},
        )
        r = client.get("/api/v1/dashboard")
        body = r.json()
        assert body["debts"]["items"] == []
        assert body["debts"]["i_owe_total"]["minor"] == 0

    def test_recent_transactions_and_top_expenses(self, seeded_client):
        client = seeded_client
        account = client.post(
            "/api/v1/accounts",
            json={"name": "Карта", "type": "bank", "currency": "RUB", "initial_balance_minor": 200_000},
        ).json()
        expense_cat = client.get("/api/v1/categories", params={"type": "expense"}).json()[0]
        this_month = datetime.now(timezone.utc).replace(day=1, hour=10).isoformat()
        client.post(
            "/api/v1/transactions",
            json={
                "account_id": account["id"],
                "category_id": expense_cat["id"],
                "type": "expense",
                "amount_minor": 12_000,
                "occurred_at": this_month,
            },
        )
        r = client.get("/api/v1/dashboard")
        body = r.json()
        assert len(body["recent_transactions"]) == 1
        assert body["recent_transactions"][0]["account_name"] == "Карта"
        assert body["recent_transactions"][0]["category_name"] == expense_cat["name"]

    def test_dashboard_unaffected_by_goals_and_budgets(self, seeded_client):
        # Дашборд не агрегирует цели/бюджеты сам — фронтенд опрашивает
        # /api/v1/goals и /api/v1/budgets отдельно. Здесь проверяем, что
        # наличие целей и бюджетов не ломает и не меняет ответ /dashboard.
        client = seeded_client
        client.post(
            "/api/v1/accounts",
            json={"name": "Карта", "type": "bank", "currency": "RUB", "initial_balance_minor": 100_000},
        )
        client.post(
            "/api/v1/goals",
            json={"name": "MacBook", "target_amount_minor": 18_000_000, "currency": "RUB"},
        )
        expense_cat = client.get("/api/v1/categories", params={"type": "expense"}).json()[0]
        client.post(
            "/api/v1/budgets",
            json={
                "category_id": expense_cat["id"],
                "amount_minor": 50_000,
                "currency": "RUB",
                "year": 2026,
                "month": 9,
            },
        )

        dashboard = client.get("/api/v1/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json()["net_worth"]["minor"] == 100_000

        goals = client.get("/api/v1/goals")
        assert goals.status_code == 200
        assert len(goals.json()) == 1

        budgets = client.get("/api/v1/budgets")
        assert budgets.status_code == 200
        assert len(budgets.json()) == 1

    def test_dashboard_empty_transactions_with_accounts_present(self, client):
        client.post(
            "/api/v1/accounts",
            json={"name": "Карта", "type": "bank", "currency": "RUB", "initial_balance_minor": 50_000},
        )
        r = client.get("/api/v1/dashboard")
        body = r.json()
        assert body["recent_transactions"] == []
        assert body["top_expenses"] == []
        assert body["net_worth"]["minor"] == 50_000
