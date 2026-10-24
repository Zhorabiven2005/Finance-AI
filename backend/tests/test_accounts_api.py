"""API-тесты счетов."""

from __future__ import annotations


def create_account(client, **overrides):
    payload = {
        "name": "Основная карта",
        "type": "bank",
        "currency": "RUB",
        "initial_balance_minor": 100_000,
        **overrides,
    }
    r = client.post("/api/v1/accounts", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


class TestCreateAccount:
    def test_create_bank_account(self, client):
        acc = create_account(client)
        assert acc["type"] == "bank"
        assert acc["currency"] == "RUB"
        assert acc["is_active"] is True
        assert acc["balance"] == {"minor": 100_000, "currency": "RUB"}

    def test_create_cash_account_zero_balance(self, client):
        acc = create_account(client, name="Кошелёк", type="cash", initial_balance_minor=0)
        assert acc["balance"]["minor"] == 0

    def test_unknown_currency_rejected(self, client):
        r = client.post(
            "/api/v1/accounts",
            json={"name": "X", "type": "cash", "currency": "XYZ", "initial_balance_minor": 0},
        )
        assert r.status_code == 400

    def test_invalid_type_rejected(self, client):
        r = client.post(
            "/api/v1/accounts",
            json={"name": "X", "type": "crypto", "currency": "RUB", "initial_balance_minor": 0},
        )
        assert r.status_code == 422

    def test_float_amount_rejected(self, client):
        r = client.post(
            "/api/v1/accounts",
            json={
                "name": "X",
                "type": "cash",
                "currency": "RUB",
                "initial_balance_minor": 100.5,
            },
        )
        assert r.status_code == 422


class TestListAndUpdateAccount:
    def test_list_accounts(self, client):
        create_account(client, name="Карта")
        create_account(client, name="Наличные", type="cash")
        r = client.get("/api/v1/accounts")
        assert r.status_code == 200
        names = {a["name"] for a in r.json()}
        assert names == {"Карта", "Наличные"}

    def test_update_account_name_and_active(self, client):
        acc = create_account(client)
        r = client.patch(
            f"/api/v1/accounts/{acc['id']}", json={"name": "Новое имя", "is_active": False}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Новое имя"
        assert body["is_active"] is False

    def test_get_missing_account_404(self, client):
        r = client.get("/api/v1/accounts/999")
        assert r.status_code == 404

    def test_list_excludes_inactive_when_requested(self, client):
        active = create_account(client, name="Активный")
        inactive = create_account(client, name="Неактивный")
        client.patch(f"/api/v1/accounts/{inactive['id']}", json={"is_active": False})
        r = client.get("/api/v1/accounts", params={"include_inactive": False})
        names = {a["name"] for a in r.json()}
        assert names == {"Активный"}


class TestDeleteAccount:
    def test_delete_unused_account(self, client):
        acc = create_account(client)
        r = client.delete(f"/api/v1/accounts/{acc['id']}")
        assert r.status_code == 204
        assert client.get(f"/api/v1/accounts/{acc['id']}").status_code == 404

    def test_delete_account_with_transactions_rejected(self, seeded_client):
        client = seeded_client
        acc = create_account(client)
        category = client.get("/api/v1/categories", params={"type": "income"}).json()[0]
        client.post(
            "/api/v1/transactions",
            json={
                "account_id": acc["id"],
                "category_id": category["id"],
                "type": "income",
                "amount_minor": 1000,
                "occurred_at": "2026-01-15T10:00:00Z",
            },
        )
        r = client.delete(f"/api/v1/accounts/{acc['id']}")
        assert r.status_code == 400
        # Регресс: ошибка должна быть информативной строкой (см. detail),
        # а не пустым телом — иначе frontend не может показать причину.
        assert isinstance(r.json()["detail"], str)
        assert r.json()["detail"]

    def test_delete_account_with_transfer_rejected(self, client):
        acc = create_account(client)
        other = create_account(client, name="Второй счёт")
        client.post(
            "/api/v1/transfers",
            json={
                "from_account_id": acc["id"],
                "to_account_id": other["id"],
                "amount_minor": 1000,
                "occurred_at": "2026-01-15T10:00:00Z",
            },
        )
        r = client.delete(f"/api/v1/accounts/{acc['id']}")
        assert r.status_code == 400

    def test_delete_account_referenced_only_by_debt_payment_returns_400_not_500(self, client):
        """Регресс: удаление счёта, привязанного только к погашению долга
        (DebtPayment.account_id), раньше падало необработанным
        IntegrityError -> HTTP 500 вместо понятной ошибки 400, потому что
        проверка на связанные данные не учитывала эту связь."""
        acc = create_account(client)
        debt = client.post(
            "/api/v1/debts",
            json={
                "counterparty_name": "Иван",
                "direction": "i_owe",
                "principal_minor": 5_000,
                "currency": "RUB",
            },
        ).json()
        client.post(
            f"/api/v1/debts/{debt['id']}/payments",
            json={
                "amount_minor": 2_000,
                "paid_at": "2026-02-01T12:00:00Z",
                "account_id": acc["id"],
            },
        )

        r = client.delete(f"/api/v1/accounts/{acc['id']}")

        assert r.status_code == 400
        assert isinstance(r.json()["detail"], str)
        # Счёт и погашение должны остаться нетронутыми.
        assert client.get(f"/api/v1/accounts/{acc['id']}").status_code == 200
        payments = client.get(f"/api/v1/debts/{debt['id']}/payments").json()
        assert len(payments) == 1
