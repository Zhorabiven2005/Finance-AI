"""API-тесты регулярных операций: CRUD, генерация, идемпотентность,
пропущенные даты, end_date."""

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
    salary = next(c for c in categories if c["name"] == "Зарплата")
    rent = next(c for c in categories if c["name"] == "Жильё")
    food = next(c for c in categories if c["name"] == "Продукты")
    return {"client": client, "account": account, "salary": salary, "rent": rent, "food": food}


def create_rule(client, **overrides):
    payload = {
        "type": "expense",
        "account_id": overrides.pop("account_id"),
        "category_id": overrides.pop("category_id"),
        "amount_minor": 3_500_000,
        "start_date": "2026-09-01",
        "frequency": "monthly",
        **overrides,
    }
    r = client.post("/api/v1/recurring-transactions", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def total_transactions(client) -> int:
    return int(client.get("/api/v1/transactions").headers["x-total-count"])


class TestCreateRule:
    def test_create_expense_rule(self, setup):
        rule = create_rule(setup["client"], account_id=setup["account"]["id"], category_id=setup["rent"]["id"])
        assert rule["type"] == "expense"
        assert rule["frequency"] == "monthly"
        assert rule["next_run_date"] == "2026-09-01"
        assert rule["is_active"] is True
        assert rule["amount"]["currency"] == "RUB"

    def test_currency_derived_from_account(self, setup):
        usd_account = setup["client"].post(
            "/api/v1/accounts",
            json={"name": "USD", "type": "bank", "currency": "USD", "initial_balance_minor": 0},
        ).json()
        rule = create_rule(setup["client"], account_id=usd_account["id"], category_id=setup["rent"]["id"])
        assert rule["amount"]["currency"] == "USD"

    def test_category_type_mismatch_rejected(self, setup):
        r = setup["client"].post(
            "/api/v1/recurring-transactions",
            json={
                "type": "expense",
                "account_id": setup["account"]["id"],
                "category_id": setup["salary"]["id"],
                "amount_minor": 1000,
                "start_date": "2026-09-01",
                "frequency": "monthly",
            },
        )
        assert r.status_code == 400

    def test_income_rule_with_income_category(self, setup):
        rule = create_rule(
            setup["client"],
            type="income",
            account_id=setup["account"]["id"],
            category_id=setup["salary"]["id"],
        )
        assert rule["type"] == "income"

    def test_end_date_before_start_date_rejected(self, setup):
        r = setup["client"].post(
            "/api/v1/recurring-transactions",
            json={
                "type": "expense",
                "account_id": setup["account"]["id"],
                "category_id": setup["rent"]["id"],
                "amount_minor": 1000,
                "start_date": "2026-09-01",
                "end_date": "2026-08-01",
                "frequency": "monthly",
            },
        )
        assert r.status_code == 400

    def test_next_run_date_defaults_to_start_date(self, setup):
        rule = create_rule(setup["client"], account_id=setup["account"]["id"], category_id=setup["rent"]["id"], start_date="2026-09-15")
        assert rule["next_run_date"] == "2026-09-15"

    def test_explicit_next_run_date_after_start(self, setup):
        rule = create_rule(
            setup["client"],
            account_id=setup["account"]["id"],
            category_id=setup["rent"]["id"],
            start_date="2026-09-01",
            next_run_date="2026-10-01",
        )
        assert rule["next_run_date"] == "2026-10-01"

    def test_float_amount_rejected(self, setup):
        r = setup["client"].post(
            "/api/v1/recurring-transactions",
            json={
                "type": "expense",
                "account_id": setup["account"]["id"],
                "category_id": setup["rent"]["id"],
                "amount_minor": 100.5,
                "start_date": "2026-09-01",
                "frequency": "monthly",
            },
        )
        assert r.status_code == 422

    def test_invalid_frequency_rejected(self, setup):
        r = setup["client"].post(
            "/api/v1/recurring-transactions",
            json={
                "type": "expense",
                "account_id": setup["account"]["id"],
                "category_id": setup["rent"]["id"],
                "amount_minor": 1000,
                "start_date": "2026-09-01",
                "frequency": "biweekly",
            },
        )
        assert r.status_code == 422


class TestUpdateAndDelete:
    def test_update_amount_and_comment(self, setup):
        rule = create_rule(setup["client"], account_id=setup["account"]["id"], category_id=setup["rent"]["id"])
        r = setup["client"].patch(
            f"/api/v1/recurring-transactions/{rule['id']}",
            json={"amount_minor": 4_000_000, "comment": "Новая аренда"},
        )
        assert r.status_code == 200
        assert r.json()["amount"]["minor"] == 4_000_000
        assert r.json()["comment"] == "Новая аренда"

    def test_deactivate_via_patch(self, setup):
        rule = create_rule(setup["client"], account_id=setup["account"]["id"], category_id=setup["rent"]["id"])
        r = setup["client"].patch(f"/api/v1/recurring-transactions/{rule['id']}", json={"is_active": False})
        assert r.json()["is_active"] is False

    def test_delete_rule_keeps_generated_transactions(self, setup):
        client = setup["client"]
        rule = create_rule(client, account_id=setup["account"]["id"], category_id=setup["rent"]["id"])
        client.post("/api/v1/recurring-transactions/process", params={"as_of": "2026-09-01"})
        count_before = total_transactions(client)
        assert count_before == 1

        r = client.delete(f"/api/v1/recurring-transactions/{rule['id']}")
        assert r.status_code == 204
        # Сгенерированная операция — обычная Transaction и не исчезает
        # вместе с правилом, которое её создало.
        assert total_transactions(client) == count_before


class TestFrequencies:
    @pytest.mark.parametrize(
        "frequency,as_of,expected_next",
        [
            ("daily", "2026-09-01", "2026-09-02"),
            ("weekly", "2026-09-01", "2026-09-08"),
            ("monthly", "2026-09-01", "2026-10-01"),
            ("yearly", "2026-09-01", "2027-09-01"),
        ],
    )
    def test_each_frequency_advances_correctly(self, setup, frequency, as_of, expected_next):
        client = setup["client"]
        rule = create_rule(
            client,
            account_id=setup["account"]["id"],
            category_id=setup["rent"]["id"],
            start_date="2026-09-01",
            frequency=frequency,
        )
        client.post("/api/v1/recurring-transactions/process", params={"as_of": as_of})
        updated = client.get(f"/api/v1/recurring-transactions/{rule['id']}").json()
        assert updated["next_run_date"] == expected_next


class TestGeneration:
    def test_process_creates_transaction_with_correct_fields(self, setup):
        client = setup["client"]
        rule = create_rule(
            client,
            type="expense",
            account_id=setup["account"]["id"],
            category_id=setup["rent"]["id"],
            amount_minor=3_500_000,
            start_date="2026-09-01",
            frequency="monthly",
        )
        client.post("/api/v1/recurring-transactions/process", params={"as_of": "2026-09-01"})
        txs = client.get("/api/v1/transactions", params={"category_id": setup["rent"]["id"]}).json()
        assert len(txs) == 1
        tx = txs[0]
        assert tx["type"] == "expense"
        assert tx["account_id"] == setup["account"]["id"]
        assert tx["amount"]["minor"] == 3_500_000
        assert tx["occurred_at"].startswith("2026-09-01")

    def test_transaction_affects_account_balance(self, setup):
        client = setup["client"]
        create_rule(
            client,
            type="income",
            account_id=setup["account"]["id"],
            category_id=setup["salary"]["id"],
            amount_minor=12_000_000,
            start_date="2026-09-01",
            frequency="monthly",
        )
        client.post("/api/v1/recurring-transactions/process", params={"as_of": "2026-09-01"})
        account = client.get(f"/api/v1/accounts/{setup['account']['id']}").json()
        assert account["balance"]["minor"] == 12_000_000

    def test_inactive_rule_not_processed(self, setup):
        client = setup["client"]
        rule = create_rule(client, account_id=setup["account"]["id"], category_id=setup["rent"]["id"])
        client.patch(f"/api/v1/recurring-transactions/{rule['id']}", json={"is_active": False})
        result = client.post("/api/v1/recurring-transactions/process", params={"as_of": "2026-09-01"}).json()
        assert result["created_transactions"] == 0

    def test_future_rule_not_processed_yet(self, setup):
        client = setup["client"]
        create_rule(
            client,
            account_id=setup["account"]["id"],
            category_id=setup["rent"]["id"],
            start_date="2026-12-01",
        )
        result = client.post("/api/v1/recurring-transactions/process", params={"as_of": "2026-09-01"}).json()
        assert result["created_transactions"] == 0


class TestIdempotency:
    def test_process_called_twice_creates_one_transaction_not_two(self, setup):
        client = setup["client"]
        create_rule(client, account_id=setup["account"]["id"], category_id=setup["rent"]["id"], start_date="2026-09-01")

        first = client.post("/api/v1/recurring-transactions/process", params={"as_of": "2026-09-01"}).json()
        assert first["created_transactions"] == 1

        second = client.post("/api/v1/recurring-transactions/process", params={"as_of": "2026-09-01"}).json()
        assert second["created_transactions"] == 0

        assert total_transactions(client) == 1

    def test_process_called_many_times_stays_idempotent(self, setup):
        client = setup["client"]
        create_rule(client, account_id=setup["account"]["id"], category_id=setup["rent"]["id"], start_date="2026-09-01")
        for _ in range(5):
            client.post("/api/v1/recurring-transactions/process", params={"as_of": "2026-09-01"})
        assert total_transactions(client) == 1

    def test_advancing_as_of_date_creates_additional_occurrence(self, setup):
        client = setup["client"]
        create_rule(client, account_id=setup["account"]["id"], category_id=setup["rent"]["id"], start_date="2026-09-01")
        client.post("/api/v1/recurring-transactions/process", params={"as_of": "2026-09-01"})
        assert total_transactions(client) == 1
        # Тот же день ещё раз — не должно создать вторую операцию.
        client.post("/api/v1/recurring-transactions/process", params={"as_of": "2026-09-01"})
        assert total_transactions(client) == 1
        # Следующий месяц наступил — новая операция должна появиться.
        client.post("/api/v1/recurring-transactions/process", params={"as_of": "2026-10-01"})
        assert total_transactions(client) == 2


class TestMissedDates:
    def test_five_missed_daily_dates_all_generated(self, setup):
        client = setup["client"]
        rule_resp = client.post(
            "/api/v1/recurring-transactions",
            json={
                "type": "expense",
                "account_id": setup["account"]["id"],
                "category_id": setup["food"]["id"],
                "amount_minor": 50000,
                "start_date": "2026-09-01",
                "frequency": "daily",
            },
        ).json()
        result = client.post(
            "/api/v1/recurring-transactions/process", params={"as_of": "2026-09-05"}
        ).json()
        assert result["created_transactions"] == 5
        assert total_transactions(client) == 5

        updated = client.get(f"/api/v1/recurring-transactions/{rule_resp['id']}").json()
        assert updated["next_run_date"] == "2026-09-06"

        # Повторный вызов на ту же дату не добавляет дублей.
        client.post("/api/v1/recurring-transactions/process", params={"as_of": "2026-09-05"})
        assert total_transactions(client) == 5


class TestEndDate:
    def test_rule_deactivated_once_next_run_passes_end_date(self, setup):
        client = setup["client"]
        rule = client.post(
            "/api/v1/recurring-transactions",
            json={
                "type": "expense",
                "account_id": setup["account"]["id"],
                "category_id": setup["rent"]["id"],
                "amount_minor": 100000,
                "start_date": "2026-09-01",
                "end_date": "2026-10-15",
                "frequency": "monthly",
            },
        ).json()

        client.post("/api/v1/recurring-transactions/process", params={"as_of": "2026-12-01"})

        updated = client.get(f"/api/v1/recurring-transactions/{rule['id']}").json()
        assert updated["is_active"] is False
        # Сгенерированы только сентябрь и октябрь (последний <= end_date),
        # ноябрьская дата уже за пределами end_date.
        assert total_transactions(client) == 2

    def test_rule_within_end_date_stays_active(self, setup):
        client = setup["client"]
        rule = client.post(
            "/api/v1/recurring-transactions",
            json={
                "type": "expense",
                "account_id": setup["account"]["id"],
                "category_id": setup["rent"]["id"],
                "amount_minor": 100000,
                "start_date": "2026-09-01",
                "end_date": "2026-12-31",
                "frequency": "monthly",
            },
        ).json()
        client.post("/api/v1/recurring-transactions/process", params={"as_of": "2026-09-01"})
        updated = client.get(f"/api/v1/recurring-transactions/{rule['id']}").json()
        assert updated["is_active"] is True


class TestAccountAndCategoryDeletionGuards:
    def test_cannot_delete_account_used_by_rule(self, setup):
        client = setup["client"]
        create_rule(client, account_id=setup["account"]["id"], category_id=setup["rent"]["id"])
        r = client.delete(f"/api/v1/accounts/{setup['account']['id']}")
        assert r.status_code == 400

    def test_cannot_delete_category_used_by_rule(self, setup):
        client = setup["client"]
        custom = client.post("/api/v1/categories", json={"name": "Абонемент", "type": "expense"}).json()
        create_rule(client, account_id=setup["account"]["id"], category_id=custom["id"])
        r = client.delete(f"/api/v1/categories/{custom['id']}")
        assert r.status_code == 400
