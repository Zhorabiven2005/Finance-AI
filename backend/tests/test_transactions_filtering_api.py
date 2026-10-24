"""API-тесты фильтрации, поиска, сортировки и пагинации операций (Stage 2A)."""

from __future__ import annotations

import pytest


@pytest.fixture()
def data(seeded_client):
    client = seeded_client
    account_a = client.post(
        "/api/v1/accounts",
        json={"name": "Карта Сбер", "type": "bank", "currency": "RUB", "initial_balance_minor": 0},
    ).json()
    account_b = client.post(
        "/api/v1/accounts",
        json={"name": "Наличные", "type": "cash", "currency": "RUB", "initial_balance_minor": 0},
    ).json()
    categories = client.get("/api/v1/categories").json()
    food = next(c for c in categories if c["name"] == "Продукты")
    transport = next(c for c in categories if c["name"] == "Транспорт")
    salary = next(c for c in categories if c["name"] == "Зарплата")

    def add(account_id, category_id, type_, amount, occurred_at, comment=None):
        r = client.post(
            "/api/v1/transactions",
            json={
                "account_id": account_id,
                "category_id": category_id,
                "type": type_,
                "amount_minor": amount,
                "occurred_at": occurred_at,
                "comment": comment,
            },
        )
        assert r.status_code == 201, r.text
        return r.json()

    tx = {
        "t1_food_a": add(account_a["id"], food["id"], "expense", 10000, "2026-01-10T12:00:00Z", "Пятёрочка"),
        "t2_transport_a": add(account_a["id"], transport["id"], "expense", 30000, "2026-01-15T12:00:00Z"),
        "t3_food_b": add(account_b["id"], food["id"], "expense", 50000, "2026-01-20T12:00:00Z"),
        "t4_salary_a": add(account_a["id"], salary["id"], "income", 1000000, "2026-01-05T12:00:00Z"),
        "t5_start_of_feb": add(account_a["id"], food["id"], "expense", 5000, "2026-02-01T00:00:00Z"),
        "t6_end_of_jan": add(account_a["id"], food["id"], "expense", 7500, "2026-01-31T23:59:59Z"),
    }
    return {
        "client": client,
        "account_a": account_a,
        "account_b": account_b,
        "food": food,
        "transport": transport,
        "salary": salary,
        "tx": tx,
    }


class TestFilterByType:
    def test_expense_only(self, data):
        r = data["client"].get("/api/v1/transactions", params={"type": "expense", "limit": 100})
        assert {t["id"] for t in r.json()} == {
            data["tx"]["t1_food_a"]["id"],
            data["tx"]["t2_transport_a"]["id"],
            data["tx"]["t3_food_b"]["id"],
            data["tx"]["t5_start_of_feb"]["id"],
            data["tx"]["t6_end_of_jan"]["id"],
        }

    def test_income_only(self, data):
        r = data["client"].get("/api/v1/transactions", params={"type": "income", "limit": 100})
        assert [t["id"] for t in r.json()] == [data["tx"]["t4_salary_a"]["id"]]


class TestFilterByAccount:
    def test_account_a_excludes_account_b(self, data):
        r = data["client"].get(
            "/api/v1/transactions", params={"account_id": data["account_a"]["id"], "limit": 100}
        )
        ids = {t["id"] for t in r.json()}
        assert data["tx"]["t3_food_b"]["id"] not in ids
        assert data["tx"]["t1_food_a"]["id"] in ids


class TestFilterByCategory:
    def test_category_food(self, data):
        r = data["client"].get(
            "/api/v1/transactions", params={"category_id": data["food"]["id"], "limit": 100}
        )
        assert {t["id"] for t in r.json()} == {
            data["tx"]["t1_food_a"]["id"],
            data["tx"]["t3_food_b"]["id"],
            data["tx"]["t5_start_of_feb"]["id"],
            data["tx"]["t6_end_of_jan"]["id"],
        }


class TestFilterByPeriod:
    def test_boundary_dates_inclusive(self, data):
        """Операция ровно в конце периода (23:59:59) включается, операция
        ровно в начале следующего периода (00:00:00) — нет."""
        r = data["client"].get(
            "/api/v1/transactions",
            params={
                "date_from": "2026-01-01T00:00:00Z",
                "date_to": "2026-01-31T23:59:59Z",
                "limit": 100,
            },
        )
        ids = {t["id"] for t in r.json()}
        assert data["tx"]["t6_end_of_jan"]["id"] in ids
        assert data["tx"]["t5_start_of_feb"]["id"] not in ids

    def test_start_boundary_exact_midnight_included(self, data):
        r = data["client"].get(
            "/api/v1/transactions",
            params={
                "date_from": "2026-02-01T00:00:00Z",
                "date_to": "2026-02-28T23:59:59Z",
                "limit": 100,
            },
        )
        ids = {t["id"] for t in r.json()}
        assert ids == {data["tx"]["t5_start_of_feb"]["id"]}

    def test_period_with_no_transactions_returns_empty(self, data):
        r = data["client"].get(
            "/api/v1/transactions",
            params={"date_from": "2020-01-01T00:00:00Z", "date_to": "2020-01-31T00:00:00Z"},
        )
        assert r.json() == []
        assert r.headers["x-total-count"] == "0"


class TestAmountRange:
    def test_amount_min_and_max(self, data):
        r = data["client"].get(
            "/api/v1/transactions",
            params={"amount_min": 10000, "amount_max": 30000, "limit": 100},
        )
        assert {t["id"] for t in r.json()} == {
            data["tx"]["t1_food_a"]["id"],
            data["tx"]["t2_transport_a"]["id"],
        }


class TestSearch:
    def test_search_by_comment_case_insensitive(self, data):
        r = data["client"].get("/api/v1/transactions", params={"search": "пятёрочка"})
        assert [t["id"] for t in r.json()] == [data["tx"]["t1_food_a"]["id"]]

    def test_search_by_comment_different_case(self, data):
        r = data["client"].get("/api/v1/transactions", params={"search": "ПЯТЁРОЧКА"})
        assert [t["id"] for t in r.json()] == [data["tx"]["t1_food_a"]["id"]]

    def test_search_by_category_name_lowercase(self, data):
        # Категория в базе называется "Продукты" — поиск должен находить её
        # по строчному "продукты" (кириллица, регистронезависимо).
        r = data["client"].get("/api/v1/transactions", params={"search": "продукты", "limit": 100})
        ids = {t["id"] for t in r.json()}
        assert data["tx"]["t1_food_a"]["id"] in ids
        assert data["tx"]["t3_food_b"]["id"] in ids
        assert data["tx"]["t2_transport_a"]["id"] not in ids

    def test_search_by_account_name(self, data):
        r = data["client"].get("/api/v1/transactions", params={"search": "наличные", "limit": 100})
        ids = {t["id"] for t in r.json()}
        assert data["tx"]["t3_food_b"]["id"] in ids
        assert data["tx"]["t1_food_a"]["id"] not in ids

    def test_search_no_match_returns_empty(self, data):
        r = data["client"].get("/api/v1/transactions", params={"search": "несуществующее"})
        assert r.json() == []


class TestSort:
    def test_sort_by_amount_ascending(self, data):
        r = data["client"].get(
            "/api/v1/transactions",
            params={"sort_by": "amount_minor", "sort_dir": "asc", "limit": 100},
        )
        amounts = [t["amount"]["minor"] for t in r.json()]
        assert amounts == sorted(amounts)

    def test_sort_by_amount_descending(self, data):
        r = data["client"].get(
            "/api/v1/transactions",
            params={"sort_by": "amount_minor", "sort_dir": "desc", "limit": 100},
        )
        amounts = [t["amount"]["minor"] for t in r.json()]
        assert amounts == sorted(amounts, reverse=True)

    def test_default_sort_is_date_descending(self, data):
        r = data["client"].get("/api/v1/transactions", params={"limit": 100})
        dates = [t["occurred_at"] for t in r.json()]
        assert dates == sorted(dates, reverse=True)


class TestPagination:
    def test_total_count_header_reflects_full_filtered_set(self, data):
        r = data["client"].get("/api/v1/transactions", params={"type": "expense", "limit": 2})
        assert r.headers["x-total-count"] == "5"
        assert len(r.json()) == 2

    def test_pages_do_not_overlap_or_skip(self, data):
        client = data["client"]
        page1 = client.get(
            "/api/v1/transactions", params={"limit": 2, "offset": 0, "sort_by": "amount_minor"}
        ).json()
        page2 = client.get(
            "/api/v1/transactions", params={"limit": 2, "offset": 2, "sort_by": "amount_minor"}
        ).json()
        page3 = client.get(
            "/api/v1/transactions", params={"limit": 2, "offset": 4, "sort_by": "amount_minor"}
        ).json()
        all_ids = [t["id"] for t in page1 + page2 + page3]
        assert len(all_ids) == len(set(all_ids)) == 6

    def test_page_size_is_clamped_to_max(self, data):
        r = data["client"].get("/api/v1/transactions", params={"limit": 100000})
        assert len(r.json()) <= 100  # MAX_PAGE_SIZE


class TestCombinedFilters:
    def test_type_account_category_and_period_together(self, data):
        r = data["client"].get(
            "/api/v1/transactions",
            params={
                "type": "expense",
                "account_id": data["account_a"]["id"],
                "category_id": data["food"]["id"],
                "date_from": "2026-01-01T00:00:00Z",
                "date_to": "2026-01-31T23:59:59Z",
            },
        )
        ids = {t["id"] for t in r.json()}
        assert ids == {data["tx"]["t1_food_a"]["id"], data["tx"]["t6_end_of_jan"]["id"]}

    def test_no_results_when_filters_contradict(self, data):
        r = data["client"].get(
            "/api/v1/transactions",
            params={"type": "income", "category_id": data["food"]["id"]},
        )
        assert r.json() == []
