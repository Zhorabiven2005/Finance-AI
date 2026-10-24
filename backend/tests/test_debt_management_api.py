"""Долги 2.0: срок, состояние срока, прогресс, история платежей, Dashboard."""

from __future__ import annotations

from datetime import date

import pytest

from app import clock

TODAY = date(2026, 10, 15)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: TODAY)


@pytest.fixture()
def account(seeded_client):
    return seeded_client.post(
        "/api/v1/accounts", json={"name": "Сбер", "type": "bank", "currency": "RUB", "initial_balance_minor": 10_000_000}
    ).json()


def make_debt(client, **over):
    payload = {"counterparty_name": "Банк", "direction": "i_owe", "principal_minor": 10_000_000, "currency": "RUB", **over}
    r = client.post("/api/v1/debts", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def pay(client, debt, amount, account=None):
    r = client.post(
        f"/api/v1/debts/{debt['id']}/payments",
        json={"amount_minor": amount, "paid_at": "2026-10-10T10:00:00Z", "account_id": account["id"] if account else None},
    )
    assert r.status_code == 201, r.text
    return r.json()


def get(client, debt):
    return client.get(f"/api/v1/debts/{debt['id']}").json()


class TestDueDate:
    def test_no_due_date(self, seeded_client):
        d = make_debt(seeded_client)
        assert (d["due_date"], d["due_state"], d["days_until_due"]) == (None, "none", None)
        assert d["created_at"]

    @pytest.mark.parametrize(
        "due, state, days",
        [("2026-10-14", "overdue", -1), ("2026-10-15", "today", 0), ("2026-10-22", "soon", 7), ("2026-10-23", "upcoming", 8)],
    )
    def test_states_at_boundaries(self, seeded_client, due, state, days):
        d = make_debt(seeded_client, due_date=due)
        assert (d["due_state"], d["days_until_due"]) == (state, days)

    def test_set_change_and_clear_due_date(self, seeded_client):
        d = make_debt(seeded_client)
        r = seeded_client.patch(f"/api/v1/debts/{d['id']}", json={"due_date": "2026-10-16"})
        assert r.status_code == 200 and r.json()["due_state"] == "soon"
        assert seeded_client.patch(f"/api/v1/debts/{d['id']}", json={"due_date": "2026-09-01"}).json()["due_state"] == "overdue"
        cleared = seeded_client.patch(f"/api/v1/debts/{d['id']}", json={"due_date": None}).json()
        assert (cleared["due_date"], cleared["due_state"]) == (None, "none")

    def test_edit_name_and_comment_keeps_amounts(self, seeded_client):
        d = make_debt(seeded_client, comment="старый")
        r = seeded_client.patch(f"/api/v1/debts/{d['id']}", json={"counterparty_name": "Тинькофф", "comment": "новый"}).json()
        assert (r["counterparty_name"], r["comment"], r["principal"]["minor"], r["direction"]) == ("Тинькофф", "новый", 10_000_000, "i_owe")

    def test_paid_debt_overrides_overdue(self, seeded_client, account):
        d = make_debt(seeded_client, due_date="2026-09-01", principal_minor=500_000)
        pay(seeded_client, d, 500_000, account)
        got = get(seeded_client, d)
        assert (got["status"], got["due_state"], got["paid_percent"]) == ("paid", "paid", 100.0)


class TestProgressAndHistory:
    def test_progress_example_from_spec(self, seeded_client, account):
        d = make_debt(seeded_client)
        pay(seeded_client, d, 4_000_000, account)
        got = get(seeded_client, d)
        assert got["principal"]["minor"] == 10_000_000
        assert got["paid"]["minor"] == 4_000_000
        assert got["remaining"]["minor"] == 6_000_000
        assert got["paid_percent"] == 40.0

    def test_history_edit_delete_keep_single_movement(self, seeded_client, account):
        d = make_debt(seeded_client)
        p = pay(seeded_client, d, 1_000_000, account)
        history = seeded_client.get(f"/api/v1/debts/{d['id']}/payments").json()
        assert len(history) == 1 and history[0]["transaction_id"]
        tx = seeded_client.get(f"/api/v1/transactions/{history[0]['transaction_id']}").json()
        assert (tx["debt_id"], tx["amount"]["minor"], tx["account_id"]) == (d["id"], 1_000_000, account["id"])

        seeded_client.patch(f"/api/v1/debts/{d['id']}/payments/{p['id']}", json={"amount_minor": 1_500_000})
        ops = seeded_client.get("/api/v1/transactions").json()
        assert [o["amount"]["minor"] for o in ops] == [1_500_000]
        assert seeded_client.get(f"/api/v1/accounts/{account['id']}").json()["balance"]["minor"] == 8_500_000
        assert get(seeded_client, d)["paid_percent"] == 15.0

        seeded_client.delete(f"/api/v1/debts/{d['id']}/payments/{p['id']}")
        assert seeded_client.get("/api/v1/transactions").json() == []
        assert seeded_client.get(f"/api/v1/accounts/{account['id']}").json()["balance"]["minor"] == 10_000_000
        assert get(seeded_client, d)["paid_percent"] == 0.0


class TestDashboardDebts:
    def test_totals_per_currency_are_never_mixed(self, seeded_client, account):
        make_debt(seeded_client, principal_minor=3_000_000, due_date="2026-10-01")
        make_debt(seeded_client, counterparty_name="Друг", direction="owed_to_me", principal_minor=500_000)
        make_debt(seeded_client, counterparty_name="Bank US", principal_minor=120_000, currency="USD", due_date="2026-10-20")
        paid = make_debt(seeded_client, counterparty_name="Погашен", principal_minor=100, due_date="2026-01-01")
        pay(seeded_client, paid, 100)

        debts = seeded_client.get("/api/v1/dashboard").json()["debts"]
        totals = {t["currency"]: (t["i_owe"]["minor"], t["owed_to_me"]["minor"]) for t in debts["totals_by_currency"]}
        assert totals == {"RUB": (3_000_000, 500_000), "USD": (120_000, 0)}
        assert debts["overdue_count"] == 1
        assert [d["counterparty_name"] for d in debts["items"]] == ["Банк", "Bank US", "Друг"]
        # Поля капитала по-прежнему только в базовой валюте.
        assert debts["i_owe_total"] == {"minor": 3_000_000, "currency": "RUB"}

    def test_net_worth_not_double_counted_after_payment(self, seeded_client, account):
        d = make_debt(seeded_client, principal_minor=3_000_000)
        before = seeded_client.get("/api/v1/dashboard").json()["net_worth"]["minor"]
        pay(seeded_client, d, 1_000_000, account)
        after = seeded_client.get("/api/v1/dashboard").json()
        assert after["net_worth"]["minor"] == before
        assert after["accounts"][0]["balance"]["minor"] == 9_000_000
        assert len(after["recent_transactions"]) == 1

    def test_debts_csv_has_due_state(self, seeded_client):
        make_debt(seeded_client, due_date="2026-10-15")
        text = seeded_client.get("/api/v1/export/debts.csv").content.decode("utf-8-sig")
        header, row = text.strip().split("\r\n")
        assert header.endswith(";due_state") and row.endswith(";today")
