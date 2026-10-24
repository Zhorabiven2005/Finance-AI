"""API-тесты финансовой аналитики (Stage 2A)."""

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

    def add(category_id, type_, amount, occurred_at, comment=None):
        r = client.post(
            "/api/v1/transactions",
            json={
                "account_id": account["id"],
                "category_id": category_id,
                "type": type_,
                "amount_minor": amount,
                "occurred_at": occurred_at,
                "comment": comment,
            },
        )
        assert r.status_code == 201, r.text
        return r.json()

    return {
        "client": client,
        "account": account,
        "food": food,
        "transport": transport,
        "salary": salary,
        "add": add,
    }


def get_analytics(client, date_from: str, date_to: str):
    r = client.get("/api/v1/analytics", params={"date_from": date_from, "date_to": date_to})
    assert r.status_code == 200, r.text
    return r.json()


class TestSummary:
    def test_income_expense_balance_and_count(self, setup):
        add = setup["add"]
        add(setup["salary"]["id"], "income", 10000000, "2026-08-05T10:00:00Z")
        add(setup["food"]["id"], "expense", 150000, "2026-08-10T10:00:00Z")
        add(setup["transport"]["id"], "expense", 50000, "2026-08-15T10:00:00Z")

        body = get_analytics(setup["client"], "2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z")
        summary = body["summary"]
        assert summary["income"]["minor"] == 10000000
        assert summary["expense"]["minor"] == 200000
        assert summary["balance"]["minor"] == 9800000
        assert summary["transaction_count"] == 3

    def test_no_hardcoded_values_reflect_real_data(self, setup):
        add = setup["add"]
        add(setup["food"]["id"], "expense", 999900, "2026-08-10T10:00:00Z")
        body = get_analytics(setup["client"], "2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z")
        assert body["summary"]["expense"]["minor"] == 999900


class TestEmptyPeriod:
    def test_empty_period_returns_zeros_not_error(self, setup):
        body = get_analytics(setup["client"], "2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z")
        assert body["summary"]["income"]["minor"] == 0
        assert body["summary"]["expense"]["minor"] == 0
        assert body["summary"]["balance"]["minor"] == 0
        assert body["summary"]["transaction_count"] == 0
        assert body["category_breakdown"] == []
        assert body["top_expenses"] == []
        # Временной ряд всё равно покрывает весь период нулями.
        assert len(body["timeseries"]) == 31
        assert all(p["income"]["minor"] == 0 and p["expense"]["minor"] == 0 for p in body["timeseries"])

    def test_invalid_period_rejected(self, setup):
        r = setup["client"].get(
            "/api/v1/analytics",
            params={"date_from": "2026-08-31T00:00:00Z", "date_to": "2026-08-01T00:00:00Z"},
        )
        assert r.status_code == 400


class TestPeriodComparison:
    def test_no_previous_data_reports_honestly(self, setup):
        add = setup["add"]
        add(setup["food"]["id"], "expense", 100000, "2026-08-10T10:00:00Z")
        body = get_analytics(setup["client"], "2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z")
        comparison = body["comparison"]
        assert comparison["has_previous_data"] is False
        assert comparison["income_change_percent"] is None
        assert comparison["expense_change_percent"] is None

    def test_comparison_with_previous_month(self, setup):
        add = setup["add"]
        # Июль: расход 100, доход 1000.
        add(setup["food"]["id"], "expense", 10000, "2026-07-15T10:00:00Z")
        add(setup["salary"]["id"], "income", 100000, "2026-07-15T10:00:00Z")
        # Август: расход 150 (+50%), доход 1200 (+20%).
        add(setup["food"]["id"], "expense", 15000, "2026-08-10T10:00:00Z")
        add(setup["salary"]["id"], "income", 120000, "2026-08-05T10:00:00Z")

        body = get_analytics(setup["client"], "2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z")
        comparison = body["comparison"]
        assert comparison["has_previous_data"] is True
        assert comparison["previous_expense"]["minor"] == 10000
        assert comparison["previous_income"]["minor"] == 100000
        assert comparison["expense_change_percent"] == pytest.approx(50.0)
        assert comparison["income_change_percent"] == pytest.approx(20.0)

    def test_comparison_period_matches_selected_period_length(self, setup):
        """Сравнение за 7-дневный период должно смотреть на предыдущие 7
        дней, а не на календарный месяц — иначе сравнение будет лживым."""
        add = setup["add"]
        # Прошлая неделя (до периода) — расход 100.
        add(setup["food"]["id"], "expense", 10000, "2026-08-07T10:00:00Z")
        # Этот период — 08-08..14-08 — расход 200.
        add(setup["food"]["id"], "expense", 20000, "2026-08-10T10:00:00Z")
        # Далеко в прошлом — не должно попасть в "предыдущий период".
        add(setup["food"]["id"], "expense", 500000, "2026-01-01T10:00:00Z")

        body = get_analytics(setup["client"], "2026-08-08T00:00:00Z", "2026-08-14T23:59:59Z")
        assert body["summary"]["expense"]["minor"] == 20000
        assert body["comparison"]["previous_expense"]["minor"] == 10000


class TestCategoryBreakdown:
    def test_percentages_sum_to_full_expense(self, setup):
        add = setup["add"]
        add(setup["food"]["id"], "expense", 30000, "2026-08-10T10:00:00Z")
        add(setup["transport"]["id"], "expense", 10000, "2026-08-11T10:00:00Z")
        body = get_analytics(setup["client"], "2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z")
        breakdown = {b["category_name"]: b for b in body["category_breakdown"]}
        assert breakdown["Продукты"]["amount"]["minor"] == 30000
        assert breakdown["Транспорт"]["amount"]["minor"] == 10000
        assert breakdown["Продукты"]["percent"] == pytest.approx(75.0)
        assert breakdown["Транспорт"]["percent"] == pytest.approx(25.0)

    def test_income_excluded_from_breakdown(self, setup):
        add = setup["add"]
        add(setup["salary"]["id"], "income", 500000, "2026-08-01T10:00:00Z")
        body = get_analytics(setup["client"], "2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z")
        assert body["category_breakdown"] == []


class TestTopExpenses:
    def test_sorted_descending_and_limited(self, setup):
        add = setup["add"]
        amounts = [5000, 90000, 30000, 12000, 45000, 1000]
        for i, amount in enumerate(amounts):
            add(setup["food"]["id"], "expense", amount, f"2026-08-{10 + i:02d}T10:00:00Z")

        body = get_analytics(setup["client"], "2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z")
        top_amounts = [t["amount"]["minor"] for t in body["top_expenses"]]
        assert top_amounts == sorted(amounts, reverse=True)[:5]

    def test_top_expense_carries_transaction_details(self, setup):
        add = setup["add"]
        add(setup["food"]["id"], "expense", 77700, "2026-08-10T10:00:00Z", comment="Ашан")
        body = get_analytics(setup["client"], "2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z")
        top = body["top_expenses"][0]
        assert top["category_name"] == "Продукты"
        assert top["account_name"] == "Карта"
        assert top["comment"] == "Ашан"


class TestGranularity:
    def test_day_range_uses_day_granularity(self, setup):
        body = get_analytics(setup["client"], "2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z")
        assert body["granularity"] == "day"
        assert len(body["timeseries"]) == 31

    def test_year_range_uses_month_granularity(self, setup):
        body = get_analytics(setup["client"], "2026-01-01T00:00:00Z", "2026-12-31T23:59:59Z")
        assert body["granularity"] == "month"
        assert len(body["timeseries"]) == 12


class TestCurrencyIsolation:
    def test_other_currency_transactions_excluded_from_base_currency_analytics(self, setup):
        usd_account = setup["client"].post(
            "/api/v1/accounts",
            json={"name": "USD", "type": "bank", "currency": "USD", "initial_balance_minor": 0},
        ).json()
        setup["client"].post(
            "/api/v1/transactions",
            json={
                "account_id": usd_account["id"],
                "category_id": setup["food"]["id"],
                "type": "expense",
                "amount_minor": 500000,
                "occurred_at": "2026-08-10T10:00:00Z",
            },
        )
        setup["add"](setup["food"]["id"], "expense", 10000, "2026-08-11T10:00:00Z")

        body = get_analytics(setup["client"], "2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z")
        # USD-расход (500000) не должен попасть в RUB-аналитику — иначе
        # валюты смешались бы в одном числе.
        assert body["currency"] == "RUB"
        assert body["summary"]["expense"]["minor"] == 10000
        assert body["summary"]["transaction_count"] == 1
