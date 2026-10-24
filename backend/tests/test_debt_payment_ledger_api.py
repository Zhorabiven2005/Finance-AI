"""Погашение долга как единое движение денег.

Платёж со счётом = ровно одна связанная Transaction. Баланс счёта, журнал,
Dashboard и аналитика читают только Transaction, поэтому задвоения нет.
"""

from __future__ import annotations

import pytest

PAY_AT = "2026-09-28T10:00:00Z"
PERIOD = {"date_from": "2026-09-01T00:00:00Z", "date_to": "2026-09-30T23:59:59Z"}


@pytest.fixture()
def setup(seeded_client):
    client = seeded_client
    account = client.post(
        "/api/v1/accounts",
        json={"name": "Сбер", "type": "bank", "currency": "RUB", "initial_balance_minor": 10_000_000},
    ).json()
    debt = client.post(
        "/api/v1/debts",
        json={
            "counterparty_name": "Банк",
            "direction": "i_owe",
            "principal_minor": 5_000_000,
            "currency": "RUB",
        },
    ).json()
    return client, account, debt


def pay(client, debt, amount, account=None, paid_at=PAY_AT, **extra):
    return client.post(
        f"/api/v1/debts/{debt['id']}/payments",
        json={
            "amount_minor": amount,
            "paid_at": paid_at,
            "account_id": account["id"] if account else None,
            **extra,
        },
    )


def balance(client, account):
    return client.get(f"/api/v1/accounts/{account['id']}").json()["balance"]["minor"]


def remaining(client, debt):
    return client.get(f"/api/v1/debts/{debt['id']}").json()["remaining"]["minor"]


def operations(client):
    return client.get("/api/v1/transactions").json()


class TestPaymentMovesMoneyOnce:
    def test_decreases_account_and_debt(self, setup):
        client, account, debt = setup
        assert pay(client, debt, 1_000_000, account).status_code == 201
        assert balance(client, account) == 9_000_000
        assert remaining(client, debt) == 4_000_000

    def test_appears_in_operations_exactly_once(self, setup):
        client, account, debt = setup
        pay(client, debt, 1_000_000, account, comment="Взнос")
        ops = operations(client)
        assert len(ops) == 1
        op = ops[0]
        assert op["type"] == "expense"
        assert op["amount"] == {"minor": 1_000_000, "currency": "RUB"}
        assert op["account_id"] == account["id"]
        assert op["debt_id"] == debt["id"]
        assert op["debt_name"] == "Банк"
        assert op["comment"] == "Взнос"
        category = client.get(f"/api/v1/categories/{op['category_id']}").json()
        assert category["name"] == "Погашение долга"

    def test_appears_in_debt_history_once_and_links_to_operation(self, setup):
        client, account, debt = setup
        pay(client, debt, 1_000_000, account)
        history = client.get(f"/api/v1/debts/{debt['id']}/payments").json()
        assert len(history) == 1
        assert history[0]["transaction_id"] == operations(client)[0]["id"]

    def test_dashboard_shows_one_movement_and_net_worth_not_double_counted(self, setup):
        client, account, debt = setup
        before = client.get("/api/v1/dashboard").json()
        pay(client, debt, 1_000_000, account)
        after = client.get("/api/v1/dashboard").json()
        assert len(after["recent_transactions"]) == 1
        recent = after["recent_transactions"][0]
        assert recent["debt_name"] == "Банк"
        assert recent["category_name"] == "Погашение долга"
        # Счёт -10 000, долг -10 000: капитал не меняется. Двойное списание
        # дало бы -10 000.
        assert after["accounts"][0]["balance"]["minor"] == 9_000_000
        assert after["debts"]["i_owe_total"]["minor"] == 4_000_000
        assert after["net_worth"]["minor"] == before["net_worth"]["minor"] == 5_000_000

    def test_analytics_counts_once(self, setup):
        client, account, debt = setup
        pay(client, debt, 1_000_000, account)
        data = client.get("/api/v1/analytics", params=PERIOD).json()
        assert data["summary"]["expense"]["minor"] == 1_000_000
        assert data["summary"]["income"]["minor"] == 0
        assert data["summary"]["transaction_count"] == 1
        assert len(data["category_breakdown"]) == 1
        assert data["category_breakdown"][0]["category_name"] == "Погашение долга"
        assert data["category_breakdown"][0]["amount"]["minor"] == 1_000_000
        assert len(data["top_expenses"]) == 1

    def test_several_payments_each_counted_once(self, setup):
        client, account, debt = setup
        pay(client, debt, 1_000_000, account)
        pay(client, debt, 250_000, account)
        pay(client, debt, 750_000, account)
        assert balance(client, account) == 10_000_000 - 2_000_000
        assert remaining(client, debt) == 3_000_000
        assert len(operations(client)) == 3
        assert len(client.get(f"/api/v1/debts/{debt['id']}/payments").json()) == 3


class TestPaymentWithoutAccount:
    def test_does_not_touch_any_account_or_journal(self, setup):
        client, account, debt = setup
        assert pay(client, debt, 1_000_000).status_code == 201
        assert balance(client, account) == 10_000_000
        assert remaining(client, debt) == 4_000_000
        assert operations(client) == []
        history = client.get(f"/api/v1/debts/{debt['id']}/payments").json()
        assert len(history) == 1
        assert history[0]["transaction_id"] is None

    def test_analytics_unaffected(self, setup):
        client, _, debt = setup
        pay(client, debt, 1_000_000)
        data = client.get("/api/v1/analytics", params=PERIOD).json()
        assert data["summary"]["transaction_count"] == 0


class TestOwedToMe:
    def test_incoming_payment_is_income(self, seeded_client):
        client = seeded_client
        account = client.post(
            "/api/v1/accounts",
            json={"name": "Карта", "type": "bank", "currency": "RUB", "initial_balance_minor": 0},
        ).json()
        debt = client.post(
            "/api/v1/debts",
            json={
                "counterparty_name": "Друг",
                "direction": "owed_to_me",
                "principal_minor": 400_000,
                "currency": "RUB",
            },
        ).json()
        pay(client, debt, 150_000, account)
        assert balance(client, account) == 150_000
        op = operations(client)[0]
        assert op["type"] == "income"
        category = client.get(f"/api/v1/categories/{op['category_id']}").json()
        assert category["name"] == "Возврат долга"
        data = client.get("/api/v1/analytics", params=PERIOD).json()
        assert data["summary"]["income"]["minor"] == 150_000
        assert data["summary"]["transaction_count"] == 1


class TestDeletePayment:
    def test_restores_account_and_removes_operation(self, setup):
        client, account, debt = setup
        payment = pay(client, debt, 1_000_000, account).json()
        assert balance(client, account) == 9_000_000
        r = client.delete(f"/api/v1/debts/{debt['id']}/payments/{payment['id']}")
        assert r.status_code == 204
        assert balance(client, account) == 10_000_000
        assert remaining(client, debt) == 5_000_000
        assert operations(client) == []
        assert client.get("/api/v1/dashboard").json()["recent_transactions"] == []
        data = client.get("/api/v1/analytics", params=PERIOD).json()
        assert data["summary"]["transaction_count"] == 0

    def test_deleting_debt_removes_its_operations(self, setup):
        client, account, debt = setup
        pay(client, debt, 1_000_000, account)
        assert client.delete(f"/api/v1/debts/{debt['id']}").status_code == 204
        assert operations(client) == []
        assert balance(client, account) == 10_000_000


class TestUpdatePayment:
    def test_amount_change_recalculates_account(self, setup):
        client, account, debt = setup
        payment = pay(client, debt, 1_000_000, account).json()
        r = client.patch(
            f"/api/v1/debts/{debt['id']}/payments/{payment['id']}",
            json={"amount_minor": 1_500_000},
        )
        assert r.status_code == 200
        assert balance(client, account) == 8_500_000
        assert remaining(client, debt) == 3_500_000
        ops = operations(client)
        assert len(ops) == 1
        assert ops[0]["amount"]["minor"] == 1_500_000

    def test_amount_can_grow_up_to_full_remaining_including_itself(self, setup):
        client, account, debt = setup
        payment = pay(client, debt, 1_000_000, account).json()
        ok = client.patch(
            f"/api/v1/debts/{debt['id']}/payments/{payment['id']}",
            json={"amount_minor": 5_000_000},
        )
        assert ok.status_code == 200
        too_much = client.patch(
            f"/api/v1/debts/{debt['id']}/payments/{payment['id']}",
            json={"amount_minor": 5_000_001},
        )
        assert too_much.status_code == 400
        assert remaining(client, debt) == 0
        assert balance(client, account) == 5_000_000

    def test_detach_account_removes_operation_and_restores_balance(self, setup):
        client, account, debt = setup
        payment = pay(client, debt, 1_000_000, account).json()
        r = client.patch(
            f"/api/v1/debts/{debt['id']}/payments/{payment['id']}",
            json={"account_id": None},
        )
        assert r.status_code == 200
        assert r.json()["account_id"] is None
        assert balance(client, account) == 10_000_000
        assert operations(client) == []
        assert remaining(client, debt) == 4_000_000

    def test_attach_account_creates_single_operation(self, setup):
        client, account, debt = setup
        payment = pay(client, debt, 1_000_000).json()
        r = client.patch(
            f"/api/v1/debts/{debt['id']}/payments/{payment['id']}",
            json={"account_id": account["id"]},
        )
        assert r.status_code == 200
        assert balance(client, account) == 9_000_000
        assert len(operations(client)) == 1

    def test_move_to_other_account(self, setup):
        client, account, debt = setup
        other = client.post(
            "/api/v1/accounts",
            json={"name": "Тинькофф", "type": "bank", "currency": "RUB", "initial_balance_minor": 2_000_000},
        ).json()
        payment = pay(client, debt, 1_000_000, account).json()
        client.patch(
            f"/api/v1/debts/{debt['id']}/payments/{payment['id']}",
            json={"account_id": other["id"]},
        )
        assert balance(client, account) == 10_000_000
        assert balance(client, other) == 1_000_000
        assert len(operations(client)) == 1

    def test_comment_and_date_propagate_to_operation(self, setup):
        client, account, debt = setup
        payment = pay(client, debt, 1_000_000, account).json()
        client.patch(
            f"/api/v1/debts/{debt['id']}/payments/{payment['id']}",
            json={"comment": "Новый", "paid_at": "2026-09-15T08:00:00Z"},
        )
        op = operations(client)[0]
        assert op["comment"] == "Новый"
        assert op["occurred_at"].startswith("2026-09-15T08:00:00")

    def test_unknown_payment_404(self, setup):
        client, _, debt = setup
        r = client.patch(f"/api/v1/debts/{debt['id']}/payments/999", json={"comment": "x"})
        assert r.status_code == 404


class TestLinkedOperationIsProtected:
    def test_cannot_delete_from_journal(self, setup):
        client, account, debt = setup
        pay(client, debt, 1_000_000, account)
        op = operations(client)[0]
        r = client.delete(f"/api/v1/transactions/{op['id']}")
        assert r.status_code == 400
        assert balance(client, account) == 9_000_000

    def test_cannot_edit_from_journal(self, setup):
        client, account, debt = setup
        pay(client, debt, 1_000_000, account)
        op = operations(client)[0]
        r = client.patch(f"/api/v1/transactions/{op['id']}", json={"amount_minor": 1})
        assert r.status_code == 400
        assert operations(client)[0]["amount"]["minor"] == 1_000_000

    def test_ordinary_transactions_still_editable(self, setup):
        client, account, _ = setup
        category = client.get("/api/v1/categories", params={"type": "expense"}).json()[0]
        tx = client.post(
            "/api/v1/transactions",
            json={
                "account_id": account["id"],
                "category_id": category["id"],
                "type": "expense",
                "amount_minor": 100,
                "occurred_at": PAY_AT,
            },
        ).json()
        assert tx["debt_id"] is None
        assert client.patch(f"/api/v1/transactions/{tx['id']}", json={"amount_minor": 200}).status_code == 200
        assert client.delete(f"/api/v1/transactions/{tx['id']}").status_code == 204


class TestValidation:
    def test_currency_mismatch_rejected_and_nothing_created(self, setup):
        client, _, debt = setup
        usd = client.post(
            "/api/v1/accounts",
            json={"name": "USD", "type": "bank", "currency": "USD", "initial_balance_minor": 100_000},
        ).json()
        r = pay(client, debt, 1_000, usd)
        assert r.status_code == 400
        assert operations(client) == []
        assert balance(client, usd) == 100_000
        assert client.get(f"/api/v1/debts/{debt['id']}/payments").json() == []

    def test_overpayment_rejected_and_nothing_created(self, setup):
        client, account, debt = setup
        assert pay(client, debt, 5_000_001, account).status_code == 400
        assert operations(client) == []
        assert balance(client, account) == 10_000_000

    def test_unknown_account_404(self, setup):
        client, _, debt = setup
        r = client.post(
            f"/api/v1/debts/{debt['id']}/payments",
            json={"amount_minor": 100, "paid_at": PAY_AT, "account_id": 9999},
        )
        assert r.status_code == 404

    def test_float_amount_rejected(self, setup):
        client, account, debt = setup
        r = client.post(
            f"/api/v1/debts/{debt['id']}/payments",
            json={"amount_minor": 10.5, "paid_at": PAY_AT, "account_id": account["id"]},
        )
        assert r.status_code == 422

    def test_large_amount(self, seeded_client):
        client = seeded_client
        account = client.post(
            "/api/v1/accounts",
            json={"name": "Big", "type": "bank", "currency": "RUB", "initial_balance_minor": 900_000_000_000},
        ).json()
        debt = client.post(
            "/api/v1/debts",
            json={
                "counterparty_name": "Big",
                "direction": "i_owe",
                "principal_minor": 500_000_000_000,
                "currency": "RUB",
            },
        ).json()
        pay(client, debt, 123_456_789_012, account)
        assert balance(client, account) == 900_000_000_000 - 123_456_789_012

    def test_works_without_seeded_categories(self, client):
        account = client.post(
            "/api/v1/accounts",
            json={"name": "A", "type": "bank", "currency": "RUB", "initial_balance_minor": 1_000},
        ).json()
        debt = client.post(
            "/api/v1/debts",
            json={"counterparty_name": "D", "direction": "i_owe", "principal_minor": 500, "currency": "RUB"},
        ).json()
        assert pay(client, debt, 500, account).status_code == 201
        assert balance(client, account) == 500
        assert len(operations(client)) == 1

    def test_account_with_payment_cannot_be_deleted(self, setup):
        client, account, debt = setup
        pay(client, debt, 1_000_000, account)
        assert client.delete(f"/api/v1/accounts/{account['id']}").status_code == 400


class TestStableOperationLink:
    """Ссылка «№N в журнале» (/transactions?tx=N) опирается на id связанной
    операции: он должен вести ровно на эту операцию, не меняться при правке
    платежа и честно отдавать 404, когда операции больше нет."""

    def history(self, client, debt):
        return client.get(f"/api/v1/debts/{debt['id']}/payments").json()

    def test_link_opens_exactly_the_payment_operation(self, setup):
        client, account, debt = setup
        pay(client, debt, 1_000_000, account, comment="Первый")
        payment = self.history(client, debt)[0]
        r = client.get(f"/api/v1/transactions/{payment['transaction_id']}")
        assert r.status_code == 200
        op = r.json()
        assert op["id"] == payment["transaction_id"]
        assert op["debt_id"] == debt["id"]
        assert op["debt_name"] == "Банк"
        assert op["account_id"] == account["id"]
        assert op["amount"] == payment["amount"]
        assert op["comment"] == "Первый"

    def test_each_payment_links_to_its_own_operation(self, setup):
        client, account, debt = setup
        pay(client, debt, 1_000_000, account)
        pay(client, debt, 2_000_000, account)
        ids = [p["transaction_id"] for p in self.history(client, debt)]
        assert len(set(ids)) == 2
        amounts = {client.get(f"/api/v1/transactions/{i}").json()["amount"]["minor"] for i in ids}
        assert amounts == {1_000_000, 2_000_000}
        assert len(operations(client)) == 2
        assert balance(client, account) == 7_000_000

    def test_editing_payment_keeps_the_same_operation_id(self, setup):
        client, account, debt = setup
        other = client.post(
            "/api/v1/accounts",
            json={"name": "Наличные", "type": "cash", "currency": "RUB", "initial_balance_minor": 3_000_000},
        ).json()
        payment = pay(client, debt, 1_000_000, account).json()
        tx_id = payment["transaction_id"]
        for change in (
            {"amount_minor": 1_500_000},
            {"comment": "Уточнил", "paid_at": "2026-09-20T09:00:00Z"},
            {"account_id": other["id"]},
        ):
            r = client.patch(f"/api/v1/debts/{debt['id']}/payments/{payment['id']}", json=change)
            assert r.status_code == 200
            assert r.json()["transaction_id"] == tx_id
        op = client.get(f"/api/v1/transactions/{tx_id}").json()
        assert op["amount"]["minor"] == 1_500_000
        assert op["account_id"] == other["id"]
        assert op["comment"] == "Уточнил"
        assert len(operations(client)) == 1
        assert balance(client, account) == 10_000_000
        assert balance(client, other) == 1_500_000

    def test_deleted_payment_operation_is_404(self, setup):
        client, account, debt = setup
        payment = pay(client, debt, 1_000_000, account).json()
        tx_id = payment["transaction_id"]
        client.delete(f"/api/v1/debts/{debt['id']}/payments/{payment['id']}")
        r = client.get(f"/api/v1/transactions/{tx_id}")
        assert r.status_code == 404
        assert r.json()["detail"] == "Операция не найдена"

    def test_deleted_debt_operation_is_404(self, setup):
        client, account, debt = setup
        tx_id = pay(client, debt, 1_000_000, account).json()["transaction_id"]
        client.delete(f"/api/v1/debts/{debt['id']}")
        assert client.get(f"/api/v1/transactions/{tx_id}").status_code == 404

    def test_detached_payment_has_no_link_and_old_operation_is_gone(self, setup):
        client, account, debt = setup
        payment = pay(client, debt, 1_000_000, account).json()
        old_id = payment["transaction_id"]
        r = client.patch(f"/api/v1/debts/{debt['id']}/payments/{payment['id']}", json={"account_id": None})
        assert r.json()["transaction_id"] is None
        assert client.get(f"/api/v1/transactions/{old_id}").status_code == 404
        r = client.patch(f"/api/v1/debts/{debt['id']}/payments/{payment['id']}", json={"account_id": account["id"]})
        new_id = r.json()["transaction_id"]
        assert new_id is not None
        assert client.get(f"/api/v1/transactions/{new_id}").json()["debt_id"] == debt["id"]
        assert len(operations(client)) == 1
        assert balance(client, account) == 9_000_000

    @pytest.mark.parametrize(
        "change",
        [
            {"comment": "из журнала"},
            {"account_id": "OTHER"},
            {"type": "income"},
            {"occurred_at": "2026-09-01T00:00:00Z"},
        ],
    )
    def test_journal_cannot_bypass_debt_rules(self, setup, change):
        client, account, debt = setup
        other = client.post(
            "/api/v1/accounts",
            json={"name": "Другой", "type": "bank", "currency": "RUB", "initial_balance_minor": 0},
        ).json()
        if change.get("account_id") == "OTHER":
            change = {"account_id": other["id"]}
        tx_id = pay(client, debt, 1_000_000, account).json()["transaction_id"]
        before = client.get(f"/api/v1/transactions/{tx_id}").json()
        r = client.patch(f"/api/v1/transactions/{tx_id}", json=change)
        assert r.status_code == 400
        assert client.get(f"/api/v1/transactions/{tx_id}").json() == before
        assert balance(client, account) == 9_000_000
        assert balance(client, other) == 0
        assert remaining(client, debt) == 4_000_000

    def test_analytics_top_expenses_point_to_the_same_single_operation(self, setup):
        client, account, debt = setup
        tx_id = pay(client, debt, 1_000_000, account).json()["transaction_id"]
        data = client.get("/api/v1/analytics", params=PERIOD).json()
        top = [t for t in data["top_expenses"] if t["transaction_id"] == tx_id]
        assert len(top) == 1
        assert top[0]["amount"] == {"minor": 1_000_000, "currency": "RUB"}
        assert len(data["top_expenses"]) == 1
        assert data["summary"]["expense"]["minor"] == 1_000_000
