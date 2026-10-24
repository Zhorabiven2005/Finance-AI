"""API-тесты долгов: создание, погашение, статусы."""

from __future__ import annotations

import pytest


def create_debt(client, **overrides):
    payload = {
        "counterparty_name": "Иван",
        "direction": "i_owe",
        "principal_minor": 50_000,
        "currency": "RUB",
        **overrides,
    }
    r = client.post("/api/v1/debts", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


class TestCreateDebt:
    def test_create_i_owe_debt(self, client):
        debt = create_debt(client)
        assert debt["direction"] == "i_owe"
        assert debt["status"] == "active"
        assert debt["remaining"]["minor"] == 50_000
        assert debt["paid"]["minor"] == 0

    def test_create_owed_to_me_debt(self, client):
        debt = create_debt(client, direction="owed_to_me", counterparty_name="Пётр")
        assert debt["direction"] == "owed_to_me"
        assert debt["status"] == "active"

    def test_debts_not_listed_as_accounts(self, client):
        create_debt(client)
        r = client.get("/api/v1/accounts")
        assert r.json() == []


class TestRepayment:
    def test_partial_payment_updates_status(self, client):
        debt = create_debt(client)
        r = client.post(
            f"/api/v1/debts/{debt['id']}/payments",
            json={"amount_minor": 20_000, "paid_at": "2026-02-01T12:00:00Z"},
        )
        assert r.status_code == 201
        updated = client.get(f"/api/v1/debts/{debt['id']}").json()
        assert updated["status"] == "partially_paid"
        assert updated["remaining"]["minor"] == 30_000
        assert updated["paid"]["minor"] == 20_000

    def test_full_payment_marks_paid(self, client):
        debt = create_debt(client)
        client.post(
            f"/api/v1/debts/{debt['id']}/payments",
            json={"amount_minor": 50_000, "paid_at": "2026-02-01T12:00:00Z"},
        )
        updated = client.get(f"/api/v1/debts/{debt['id']}").json()
        assert updated["status"] == "paid"
        assert updated["remaining"]["minor"] == 0

    def test_multiple_partial_payments_sum_correctly(self, client):
        debt = create_debt(client, principal_minor=10_000)
        for amount in (2_000, 3_000, 1_500):
            client.post(
                f"/api/v1/debts/{debt['id']}/payments",
                json={"amount_minor": amount, "paid_at": "2026-02-01T12:00:00Z"},
            )
        updated = client.get(f"/api/v1/debts/{debt['id']}").json()
        assert updated["paid"]["minor"] == 6_500
        assert updated["remaining"]["minor"] == 3_500
        assert updated["status"] == "partially_paid"

    def test_overpayment_rejected(self, client):
        debt = create_debt(client, principal_minor=1_000)
        r = client.post(
            f"/api/v1/debts/{debt['id']}/payments",
            json={"amount_minor": 1_500, "paid_at": "2026-02-01T12:00:00Z"},
        )
        assert r.status_code == 400
        # Долг не должен измениться после отклонённого платежа.
        unchanged = client.get(f"/api/v1/debts/{debt['id']}").json()
        assert unchanged["remaining"]["minor"] == 1_000

    def test_payment_linked_to_account_moves_balance(self, client):
        account = client.post(
            "/api/v1/accounts",
            json={"name": "Карта", "type": "bank", "currency": "RUB", "initial_balance_minor": 100_000},
        ).json()
        debt = create_debt(client, direction="i_owe", principal_minor=20_000)
        client.post(
            f"/api/v1/debts/{debt['id']}/payments",
            json={
                "amount_minor": 20_000,
                "paid_at": "2026-02-01T12:00:00Z",
                "account_id": account["id"],
            },
        )
        updated_account = client.get(f"/api/v1/accounts/{account['id']}").json()
        # Я должен был 20000 — погасил со своего счёта, баланс уменьшился.
        assert updated_account["balance"]["minor"] == 80_000

    def test_owed_to_me_payment_increases_account_balance(self, client):
        account = client.post(
            "/api/v1/accounts",
            json={"name": "Карта", "type": "bank", "currency": "RUB", "initial_balance_minor": 0},
        ).json()
        debt = create_debt(
            client, direction="owed_to_me", principal_minor=15_000, counterparty_name="Мария"
        )
        client.post(
            f"/api/v1/debts/{debt['id']}/payments",
            json={
                "amount_minor": 15_000,
                "paid_at": "2026-02-01T12:00:00Z",
                "account_id": account["id"],
            },
        )
        updated_account = client.get(f"/api/v1/accounts/{account['id']}").json()
        assert updated_account["balance"]["minor"] == 15_000


class TestDeletePayment:
    def test_deleting_payment_restores_remaining(self, client):
        debt = create_debt(client, principal_minor=10_000)
        payment = client.post(
            f"/api/v1/debts/{debt['id']}/payments",
            json={"amount_minor": 4_000, "paid_at": "2026-02-01T12:00:00Z"},
        ).json()
        r = client.delete(f"/api/v1/debts/{debt['id']}/payments/{payment['id']}")
        assert r.status_code == 204
        updated = client.get(f"/api/v1/debts/{debt['id']}").json()
        assert updated["remaining"]["minor"] == 10_000
        assert updated["status"] == "active"


class TestValidation:
    def test_float_principal_rejected(self, client):
        r = client.post(
            "/api/v1/debts",
            json={
                "counterparty_name": "X",
                "direction": "i_owe",
                "principal_minor": 100.5,
                "currency": "RUB",
            },
        )
        assert r.status_code == 422

    def test_negative_principal_rejected(self, client):
        r = client.post(
            "/api/v1/debts",
            json={
                "counterparty_name": "X",
                "direction": "i_owe",
                "principal_minor": -100,
                "currency": "RUB",
            },
        )
        assert r.status_code == 422
