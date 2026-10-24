"""Иконка категории: выбор, сохранение, отдача во всех экранах."""

from __future__ import annotations


def create(client, **extra):
    return client.post("/api/v1/categories", json={"name": "Игры", "type": "expense", **extra})


class TestCategoryIcon:
    def test_icon_selected_on_create_persists(self, client):
        r = create(client, icon="gamepad-2")
        assert r.status_code == 201
        assert r.json()["icon"] == "gamepad-2"
        got = client.get(f"/api/v1/categories/{r.json()['id']}").json()
        assert got["icon"] == "gamepad-2"
        listed = next(c for c in client.get("/api/v1/categories").json() if c["id"] == got["id"])
        assert listed["icon"] == "gamepad-2"

    def test_create_without_icon_has_null_fallback(self, client):
        assert create(client).json()["icon"] is None

    def test_icon_can_be_changed_and_cleared(self, client):
        cat = create(client, icon="car").json()
        changed = client.patch(f"/api/v1/categories/{cat['id']}", json={"icon": "plane"}).json()
        assert changed["icon"] == "plane"
        cleared = client.patch(f"/api/v1/categories/{cat['id']}", json={"icon": None}).json()
        assert cleared["icon"] is None

    def test_other_edits_keep_icon(self, client):
        cat = create(client, icon="car").json()
        renamed = client.patch(f"/api/v1/categories/{cat['id']}", json={"name": "Авто"}).json()
        assert renamed["icon"] == "car"

    def test_emoji_and_garbage_icons_rejected(self, client):
        assert create(client, icon="🛒").status_code == 422
        assert create(client, icon="Has Space").status_code == 422
        assert create(client, icon="x" * 51).status_code == 422

    def test_archived_category_preserves_icon(self, client):
        cat = create(client, icon="heart").json()
        client.patch(f"/api/v1/categories/{cat['id']}", json={"is_archived": True})
        archived = next(
            c
            for c in client.get("/api/v1/categories", params={"include_archived": True}).json()
            if c["id"] == cat["id"]
        )
        assert archived["is_archived"] is True
        assert archived["icon"] == "heart"

    def test_default_categories_keep_their_existing_icon(self, seeded_client):
        defaults = seeded_client.get("/api/v1/categories").json()
        assert all(c["icon"] for c in defaults if c["is_default"])

    def test_icon_reaches_dashboard_budgets_and_analytics(self, seeded_client):
        client = seeded_client
        account = client.post(
            "/api/v1/accounts",
            json={"name": "К", "type": "bank", "currency": "RUB", "initial_balance_minor": 100_000},
        ).json()
        cat = create(client, icon="dumbbell").json()
        client.post(
            "/api/v1/transactions",
            json={
                "account_id": account["id"],
                "category_id": cat["id"],
                "type": "expense",
                "amount_minor": 5_000,
                "occurred_at": "2026-09-10T10:00:00Z",
            },
        )
        client.post(
            "/api/v1/budgets",
            json={
                "category_id": cat["id"],
                "amount_minor": 10_000,
                "currency": "RUB",
                "year": 2026,
                "month": 9,
            },
        )
        analytics = client.get(
            "/api/v1/analytics",
            params={"date_from": "2026-09-01T00:00:00Z", "date_to": "2026-09-30T23:59:59Z"},
        ).json()
        assert analytics["category_breakdown"][0]["category_icon"] == "dumbbell"
        assert analytics["top_expenses"][0]["category_icon"] == "dumbbell"
        dashboard = client.get("/api/v1/dashboard").json()
        assert dashboard["recent_transactions"][0]["category_icon"] == "dumbbell"
        assert client.get("/api/v1/budgets").json()[0]["category_icon"] == "dumbbell"
