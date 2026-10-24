"""API-тесты переводов между счетами."""

from __future__ import annotations

import pytest


@pytest.fixture()
def accounts(client):
    a = client.post(
        "/api/v1/accounts",
        json={"name": "Счёт А", "type": "bank", "currency": "RUB", "initial_balance_minor": 100_000},
    ).json()
    b = client.post(
        "/api/v1/accounts",
        json={"name": "Счёт Б", "type": "cash", "currency": "RUB", "initial_balance_minor": 20_000},
    ).json()
    return a, b


def balance(client, account_id: int) -> int:
    return client.get(f"/api/v1/accounts/{account_id}").json()["balance"]["minor"]


class TestCreateTransfer:
    def test_transfer_moves_money_between_accounts(self, client, accounts):
        a, b = accounts
        r = client.post(
            "/api/v1/transfers",
            json={
                "from_account_id": a["id"],
                "to_account_id": b["id"],
                "amount_minor": 30_000,
                "occurred_at": "2026-01-12T10:00:00Z",
            },
        )
        assert r.status_code == 201
        assert balance(client, a["id"]) == 70_000
        assert balance(client, b["id"]) == 50_000

    def test_transfer_total_money_is_conserved(self, client, accounts):
        a, b = accounts
        total_before = balance(client, a["id"]) + balance(client, b["id"])
        client.post(
            "/api/v1/transfers",
            json={
                "from_account_id": a["id"],
                "to_account_id": b["id"],
                "amount_minor": 12_345,
                "occurred_at": "2026-01-12T10:00:00Z",
            },
        )
        total_after = balance(client, a["id"]) + balance(client, b["id"])
        assert total_before == total_after

    def test_same_account_rejected(self, client, accounts):
        a, _ = accounts
        r = client.post(
            "/api/v1/transfers",
            json={
                "from_account_id": a["id"],
                "to_account_id": a["id"],
                "amount_minor": 100,
                "occurred_at": "2026-01-12T10:00:00Z",
            },
        )
        assert r.status_code == 400

    def test_currency_mismatch_rejected(self, client, accounts):
        a, _ = accounts
        usd_account = client.post(
            "/api/v1/accounts",
            json={"name": "USD", "type": "bank", "currency": "USD", "initial_balance_minor": 0},
        ).json()
        r = client.post(
            "/api/v1/transfers",
            json={
                "from_account_id": a["id"],
                "to_account_id": usd_account["id"],
                "amount_minor": 100,
                "occurred_at": "2026-01-12T10:00:00Z",
            },
        )
        assert r.status_code == 400


class TestTransferIsNotIncomeOrExpense:
    def test_transfer_not_listed_as_transaction(self, client, accounts):
        a, b = accounts
        client.post(
            "/api/v1/transfers",
            json={
                "from_account_id": a["id"],
                "to_account_id": b["id"],
                "amount_minor": 5000,
                "occurred_at": "2026-01-12T10:00:00Z",
            },
        )
        r = client.get("/api/v1/transactions")
        assert r.json() == []


class TestDeleteTransfer:
    def test_delete_reverts_balances(self, client, accounts):
        a, b = accounts
        before_a, before_b = balance(client, a["id"]), balance(client, b["id"])
        transfer = client.post(
            "/api/v1/transfers",
            json={
                "from_account_id": a["id"],
                "to_account_id": b["id"],
                "amount_minor": 8_000,
                "occurred_at": "2026-01-12T10:00:00Z",
            },
        ).json()
        r = client.delete(f"/api/v1/transfers/{transfer['id']}")
        assert r.status_code == 204
        assert balance(client, a["id"]) == before_a
        assert balance(client, b["id"]) == before_b
