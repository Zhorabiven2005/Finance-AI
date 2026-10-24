"""API-тесты категорий."""

from __future__ import annotations


class TestDefaultCategories:
    def test_seed_has_more_than_six_categories(self, seeded_client):
        r = seeded_client.get("/api/v1/categories")
        assert r.status_code == 200
        assert len(r.json()) > 6

    def test_seed_has_both_types(self, seeded_client):
        r = seeded_client.get("/api/v1/categories")
        types = {c["type"] for c in r.json()}
        assert types == {"income", "expense"}

    def test_filter_by_type(self, seeded_client):
        r = seeded_client.get("/api/v1/categories", params={"type": "income"})
        assert all(c["type"] == "income" for c in r.json())
        assert len(r.json()) > 0


class TestCustomCategories:
    def test_create_custom_category(self, client):
        r = client.post(
            "/api/v1/categories", json={"name": "Моя категория", "type": "expense"}
        )
        assert r.status_code == 201
        body = r.json()
        assert body["is_default"] is False
        assert body["name"] == "Моя категория"

    def test_duplicate_name_and_type_rejected(self, client):
        client.post("/api/v1/categories", json={"name": "Хобби", "type": "expense"})
        r = client.post("/api/v1/categories", json={"name": "Хобби", "type": "expense"})
        assert r.status_code == 400

    def test_same_name_different_type_allowed(self, client):
        r1 = client.post("/api/v1/categories", json={"name": "Прочее", "type": "expense"})
        r2 = client.post("/api/v1/categories", json={"name": "Прочее", "type": "income"})
        assert r1.status_code == 201
        assert r2.status_code == 201

    def test_subcategory_with_parent(self, client):
        parent = client.post(
            "/api/v1/categories", json={"name": "Транспорт", "type": "expense"}
        ).json()
        child = client.post(
            "/api/v1/categories",
            json={"name": "Такси", "type": "expense", "parent_id": parent["id"]},
        )
        assert child.status_code == 201
        assert child.json()["parent_id"] == parent["id"]

    def test_subcategory_type_mismatch_rejected(self, client):
        parent = client.post(
            "/api/v1/categories", json={"name": "Зарплата2", "type": "income"}
        ).json()
        r = client.post(
            "/api/v1/categories",
            json={"name": "Такси2", "type": "expense", "parent_id": parent["id"]},
        )
        assert r.status_code == 400


class TestDeleteCategory:
    def test_delete_unused_custom_category(self, client):
        cat = client.post(
            "/api/v1/categories", json={"name": "Временная", "type": "expense"}
        ).json()
        r = client.delete(f"/api/v1/categories/{cat['id']}")
        assert r.status_code == 204

    def test_delete_default_category_rejected(self, seeded_client):
        cat = seeded_client.get("/api/v1/categories").json()[0]
        r = seeded_client.delete(f"/api/v1/categories/{cat['id']}")
        assert r.status_code == 400

    def test_delete_used_category_rejected(self, seeded_client):
        client = seeded_client
        account = client.post(
            "/api/v1/accounts",
            json={"name": "Карта", "type": "bank", "currency": "RUB", "initial_balance_minor": 0},
        ).json()
        category = client.post(
            "/api/v1/categories", json={"name": "Используемая", "type": "expense"}
        ).json()
        client.post(
            "/api/v1/transactions",
            json={
                "account_id": account["id"],
                "category_id": category["id"],
                "type": "expense",
                "amount_minor": 500,
                "occurred_at": "2026-01-15T10:00:00Z",
            },
        )
        r = client.delete(f"/api/v1/categories/{category['id']}")
        assert r.status_code == 400


class TestSubcategoryDepth:
    def test_grandchild_rejected(self, client):
        parent = client.post(
            "/api/v1/categories", json={"name": "Родитель", "type": "expense"}
        ).json()
        child = client.post(
            "/api/v1/categories",
            json={"name": "Ребёнок", "type": "expense", "parent_id": parent["id"]},
        ).json()
        r = client.post(
            "/api/v1/categories",
            json={"name": "Внук", "type": "expense", "parent_id": child["id"]},
        )
        assert r.status_code == 400

    def test_reparenting_to_grandchild_rejected_via_update(self, client):
        parent = client.post(
            "/api/v1/categories", json={"name": "Родитель2", "type": "expense"}
        ).json()
        child = client.post(
            "/api/v1/categories",
            json={"name": "Ребёнок2", "type": "expense", "parent_id": parent["id"]},
        ).json()
        other = client.post(
            "/api/v1/categories", json={"name": "Другая", "type": "expense"}
        ).json()
        r = client.patch(f"/api/v1/categories/{other['id']}", json={"parent_id": child["id"]})
        assert r.status_code == 400

    def test_category_with_children_cannot_become_subcategory(self, client):
        parent = client.post(
            "/api/v1/categories", json={"name": "Родитель3", "type": "expense"}
        ).json()
        client.post(
            "/api/v1/categories",
            json={"name": "Ребёнок3", "type": "expense", "parent_id": parent["id"]},
        )
        other = client.post(
            "/api/v1/categories", json={"name": "Другая3", "type": "expense"}
        ).json()
        r = client.patch(f"/api/v1/categories/{parent['id']}", json={"parent_id": other["id"]})
        assert r.status_code == 400


class TestEditCategory:
    def test_edit_name_icon(self, client):
        cat = client.post(
            "/api/v1/categories", json={"name": "Старое", "type": "expense"}
        ).json()
        r = client.patch(
            f"/api/v1/categories/{cat['id']}", json={"name": "Новое", "icon": "car"}
        )
        assert r.status_code == 200
        assert r.json()["name"] == "Новое"
        assert r.json()["icon"] == "car"

    def test_edit_parent(self, client):
        parent_a = client.post(
            "/api/v1/categories", json={"name": "ГруппаА", "type": "expense"}
        ).json()
        parent_b = client.post(
            "/api/v1/categories", json={"name": "ГруппаБ", "type": "expense"}
        ).json()
        child = client.post(
            "/api/v1/categories",
            json={"name": "Дитя", "type": "expense", "parent_id": parent_a["id"]},
        ).json()
        r = client.patch(f"/api/v1/categories/{child['id']}", json={"parent_id": parent_b["id"]})
        assert r.status_code == 200
        assert r.json()["parent_id"] == parent_b["id"]

    def test_change_type_when_unused_allowed(self, client):
        cat = client.post(
            "/api/v1/categories", json={"name": "Свободная", "type": "expense"}
        ).json()
        r = client.patch(f"/api/v1/categories/{cat['id']}", json={"type": "income"})
        assert r.status_code == 200
        assert r.json()["type"] == "income"

    def test_change_type_when_used_rejected(self, seeded_client):
        client = seeded_client
        account = client.post(
            "/api/v1/accounts",
            json={"name": "Карта2", "type": "bank", "currency": "RUB", "initial_balance_minor": 0},
        ).json()
        category = client.post(
            "/api/v1/categories", json={"name": "Используемая2", "type": "expense"}
        ).json()
        client.post(
            "/api/v1/transactions",
            json={
                "account_id": account["id"],
                "category_id": category["id"],
                "type": "expense",
                "amount_minor": 500,
                "occurred_at": "2026-01-15T10:00:00Z",
            },
        )
        r = client.patch(f"/api/v1/categories/{category['id']}", json={"type": "income"})
        assert r.status_code == 400


class TestArchiveCategory:
    def test_archive_category(self, client):
        cat = client.post(
            "/api/v1/categories", json={"name": "Архивируемая", "type": "expense"}
        ).json()
        r = client.patch(f"/api/v1/categories/{cat['id']}", json={"is_archived": True})
        assert r.status_code == 200
        assert r.json()["is_archived"] is True

    def test_archived_excluded_from_default_list(self, client):
        cat = client.post(
            "/api/v1/categories", json={"name": "СкрытаяПоУмолчанию", "type": "expense"}
        ).json()
        client.patch(f"/api/v1/categories/{cat['id']}", json={"is_archived": True})
        r = client.get("/api/v1/categories")
        assert cat["id"] not in [c["id"] for c in r.json()]

    def test_archived_included_with_flag(self, client):
        cat = client.post(
            "/api/v1/categories", json={"name": "ВидимаяСФлагом", "type": "expense"}
        ).json()
        client.patch(f"/api/v1/categories/{cat['id']}", json={"is_archived": True})
        r = client.get("/api/v1/categories", params={"include_archived": True})
        assert cat["id"] in [c["id"] for c in r.json()]

    def test_historical_transaction_still_shows_archived_category(self, client):
        account = client.post(
            "/api/v1/accounts",
            json={"name": "Карта3", "type": "bank", "currency": "RUB", "initial_balance_minor": 0},
        ).json()
        category = client.post(
            "/api/v1/categories", json={"name": "БудетАрхивирована", "type": "expense"}
        ).json()
        txn = client.post(
            "/api/v1/transactions",
            json={
                "account_id": account["id"],
                "category_id": category["id"],
                "type": "expense",
                "amount_minor": 500,
                "occurred_at": "2026-01-15T10:00:00Z",
            },
        ).json()
        client.patch(f"/api/v1/categories/{category['id']}", json={"is_archived": True})
        r = client.get(f"/api/v1/transactions/{txn['id']}")
        assert r.status_code == 200
        assert r.json()["category_id"] == category["id"]

    def test_archiving_used_category_allowed(self, seeded_client):
        client = seeded_client
        account = client.post(
            "/api/v1/accounts",
            json={"name": "Карта4", "type": "bank", "currency": "RUB", "initial_balance_minor": 0},
        ).json()
        category = client.post(
            "/api/v1/categories", json={"name": "ИспользуемаяАрхив", "type": "expense"}
        ).json()
        client.post(
            "/api/v1/transactions",
            json={
                "account_id": account["id"],
                "category_id": category["id"],
                "type": "expense",
                "amount_minor": 500,
                "occurred_at": "2026-01-15T10:00:00Z",
            },
        )
        r = client.patch(f"/api/v1/categories/{category['id']}", json={"is_archived": True})
        assert r.status_code == 200
        assert r.json()["is_archived"] is True

    def test_delete_still_blocked_for_used_category_even_if_archived(self, seeded_client):
        client = seeded_client
        account = client.post(
            "/api/v1/accounts",
            json={"name": "Карта5", "type": "bank", "currency": "RUB", "initial_balance_minor": 0},
        ).json()
        category = client.post(
            "/api/v1/categories", json={"name": "АрхивНеУдалить", "type": "expense"}
        ).json()
        client.post(
            "/api/v1/transactions",
            json={
                "account_id": account["id"],
                "category_id": category["id"],
                "type": "expense",
                "amount_minor": 500,
                "occurred_at": "2026-01-15T10:00:00Z",
            },
        )
        client.patch(f"/api/v1/categories/{category['id']}", json={"is_archived": True})
        r = client.delete(f"/api/v1/categories/{category['id']}")
        assert r.status_code == 400
