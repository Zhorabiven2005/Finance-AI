"""Центр уведомлений и engine через API: генерация, идемпотентность,
удаление без возврата, закрытие неактуальных, очистка, параллельный запуск."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app import clock
from app.db.models import Notification
from app.notifications import service

TODAY = date(2026, 10, 15)


@pytest.fixture()
def today(monkeypatch):
    state = {"value": TODAY}
    monkeypatch.setattr(clock, "today", lambda: state["value"])
    return state


@pytest.fixture()
def client(seeded_client, today):
    return seeded_client


@pytest.fixture()
def account(client):
    return client.post(
        "/api/v1/accounts", json={"name": "Сбер", "type": "bank", "currency": "RUB", "initial_balance_minor": 10_000_000}
    ).json()


def check(client):
    r = client.post("/api/v1/notifications/check")
    assert r.status_code == 200, r.text
    return r.json()


def listing(client, status="all"):
    return client.get("/api/v1/notifications", params={"status": status}).json()


def unread(client):
    return client.get("/api/v1/notifications/unread-count").json()["unread"]


def make_debt(client, due, **over):
    payload = {"counterparty_name": "Банк", "direction": "i_owe", "principal_minor": 1_000_000, "currency": "RUB", "due_date": due, **over}
    return client.post("/api/v1/debts", json=payload).json()


def expense(client, account, category, amount, at):
    r = client.post(
        "/api/v1/transactions",
        json={"account_id": account["id"], "category_id": category["id"], "type": "expense", "amount_minor": amount, "occurred_at": at},
    )
    assert r.status_code == 201, r.text


def food(client):
    return next(c for c in client.get("/api/v1/categories").json() if c["name"] == "Продукты")


class TestEmptyAndBasics:
    def test_empty_state(self, client):
        assert listing(client) == []
        assert unread(client) == 0
        assert check(client) == {"created": 0, "resolved": 0, "reactivated": 0, "purged": 0}

    def test_mark_read_mark_all_and_delete(self, client):
        make_debt(client, "2026-10-14")
        make_debt(client, "2026-10-15", counterparty_name="Друг")
        check(client)
        items = listing(client)
        assert len(items) == 2 and unread(client) == 2
        assert all(not n["is_read"] and n["is_active"] for n in items)

        r = client.post(f"/api/v1/notifications/{items[0]['id']}/read")
        assert r.status_code == 200 and r.json()["is_read"] is True
        assert unread(client) == 1
        assert [n["id"] for n in listing(client, "unread")] == [items[1]["id"]]

        assert client.post("/api/v1/notifications/read-all").json() == {"unread": 0}
        assert unread(client) == 0

        assert client.delete(f"/api/v1/notifications/{items[0]['id']}").status_code == 204
        assert [n["id"] for n in listing(client)] == [items[1]["id"]]
        assert client.post(f"/api/v1/notifications/{items[0]['id']}/read").status_code == 404
        assert client.delete(f"/api/v1/notifications/{items[0]['id']}").status_code == 404

    def test_unknown_id_404(self, client):
        assert client.post("/api/v1/notifications/999/read").status_code == 404


class TestEachTypeViaEngine:
    def test_debt_due_soon_today_overdue(self, client):
        make_debt(client, "2026-10-20", counterparty_name="Скоро")
        make_debt(client, "2026-10-15", counterparty_name="Сегодня")
        make_debt(client, "2026-10-01", counterparty_name="Просрочен")
        make_debt(client, "2026-12-01", counterparty_name="Далеко")
        make_debt(client, None, counterparty_name="Без срока")
        assert check(client)["created"] == 3
        types = sorted((n["type"], n["severity"]) for n in listing(client))
        assert types == [("debt_due", "info"), ("debt_due", "warning"), ("debt_overdue", "danger")]
        assert all(n["entity_type"] == "debt" and n["entity_exists"] for n in listing(client))

    def test_budget_warning_then_exceeded_resolves_warning(self, client, account):
        cat = food(client)
        client.post("/api/v1/budgets", json={"category_id": cat["id"], "amount_minor": 100_000, "currency": "RUB", "year": 2026, "month": 10})
        expense(client, account, cat, 85_000, "2026-10-05T10:00:00Z")
        check(client)
        [warning] = listing(client)
        assert warning["type"] == "budget_warning" and warning["is_active"]

        expense(client, account, cat, 20_000, "2026-10-06T10:00:00Z")
        result = check(client)
        assert (result["created"], result["resolved"]) == (1, 1)
        by_type = {n["type"]: n for n in listing(client)}
        assert by_type["budget_exceeded"]["is_active"] is True
        assert by_type["budget_warning"]["is_active"] is False  # не противоречат друг другу
        assert unread(client) == 1

    def test_spending_increased_per_currency(self, client, account):
        usd = client.post("/api/v1/accounts", json={"name": "USD", "type": "bank", "currency": "USD", "initial_balance_minor": 0}).json()
        cat = food(client)
        expense(client, account, cat, 100_000, "2026-08-10T10:00:00Z")
        expense(client, account, cat, 200_000, "2026-09-10T10:00:00Z")
        expense(client, usd, cat, 1_000, "2026-08-10T10:00:00Z")
        expense(client, usd, cat, 1_100, "2026-09-10T10:00:00Z")  # +10% — ниже порога
        check(client)
        [n] = listing(client)
        assert (n["type"], n["entity_type"], n["entity_exists"]) == ("spending_increased", "analytics", True)
        assert n["data"]["current"] == {"minor": 200_000, "currency": "RUB"}
        assert n["data"]["growth_percent"] == 100

    def test_spending_without_previous_period(self, client, account):
        expense(client, account, food(client), 500_000, "2026-09-10T10:00:00Z")
        check(client)
        assert listing(client) == []

    def test_recurring_due_and_missed(self, client, account, today):
        cat = food(client)
        client.post(
            "/api/v1/recurring-transactions",
            json={"type": "expense", "account_id": account["id"], "category_id": cat["id"], "amount_minor": 50_000, "start_date": "2026-10-16", "frequency": "monthly"},
        )
        check(client)
        [due] = listing(client)
        assert due["type"] == "recurring_transaction_due" and due["entity_type"] == "recurring_transaction"

        today["value"] = date(2026, 10, 17)  # дата прошла, операция не проведена
        result = check(client)
        assert (result["created"], result["resolved"]) == (1, 1)
        active = [n for n in listing(client) if n["is_active"]]
        assert [n["type"] for n in active] == ["recurring_transaction_missed"]

        client.post("/api/v1/recurring-transactions/process", params={"as_of": "2026-10-17"})
        check(client)
        assert [n for n in listing(client) if n["is_active"]] == []


class TestIdempotencyAndLifecycle:
    def test_repeated_generation_creates_no_duplicates(self, client):
        make_debt(client, "2026-10-01")
        assert check(client)["created"] == 1
        for _ in range(3):
            assert check(client) == {"created": 0, "resolved": 0, "reactivated": 0, "purged": 0}
        assert len(listing(client)) == 1

    def test_deleted_notification_is_not_recreated(self, client):
        make_debt(client, "2026-10-01")
        check(client)
        [n] = listing(client)
        client.delete(f"/api/v1/notifications/{n['id']}")
        assert check(client)["created"] == 0
        assert listing(client) == [] and unread(client) == 0

    def test_status_change_resolves_and_reactivates(self, client, account):
        d = make_debt(client, "2026-10-01")
        check(client)
        p = client.post(f"/api/v1/debts/{d['id']}/payments", json={"amount_minor": 1_000_000, "paid_at": "2026-10-15T09:00:00Z", "account_id": account["id"]}).json()
        assert check(client)["resolved"] == 1
        [n] = listing(client)
        assert n["is_active"] is False and unread(client) == 0

        client.delete(f"/api/v1/debts/{d['id']}/payments/{p['id']}")  # снова не погашен
        result = check(client)
        assert (result["created"], result["reactivated"]) == (0, 1)
        assert listing(client)[0]["is_active"] is True and unread(client) == 1

    def test_due_date_change_is_a_new_event(self, client):
        d = make_debt(client, "2026-10-01")
        check(client)
        client.patch(f"/api/v1/debts/{d['id']}", json={"due_date": "2026-10-16"})
        result = check(client)
        assert (result["created"], result["resolved"]) == (1, 1)
        active = [n for n in listing(client) if n["is_active"]]
        assert [n["type"] for n in active] == ["debt_due"]

    def test_soon_moves_to_today_then_overdue(self, client, today):
        make_debt(client, "2026-10-17")
        check(client)
        today["value"] = date(2026, 10, 17)
        check(client)
        today["value"] = date(2026, 10, 18)
        check(client)
        active = [n["type"] for n in listing(client) if n["is_active"]]
        assert active == ["debt_overdue"]
        assert len(listing(client)) == 3  # история: скоро, сегодня, просрочен

    def test_deleted_entity_link(self, client):
        d = make_debt(client, "2026-10-01")
        check(client)
        client.delete(f"/api/v1/debts/{d['id']}")
        check(client)
        [n] = listing(client)
        assert n["entity_exists"] is False and n["is_active"] is False

    def test_no_mass_historical_notifications(self, client, account):
        cat = food(client)
        # Год истории: долги с давно прошедшими сроками, бюджеты прошлых
        # месяцев с перерасходом, рост расходов каждый месяц.
        for m in range(1, 10):
            client.post("/api/v1/budgets", json={"category_id": cat["id"], "amount_minor": 100, "currency": "RUB", "year": 2026, "month": m})
            expense(client, account, cat, 1_000 * 2**m, f"2026-{m:02d}-10T10:00:00Z")
        for i in range(3):
            make_debt(client, f"2025-0{i + 1}-01", counterparty_name=f"Старый {i}")
        check(client)
        types = sorted(n["type"] for n in listing(client))
        # По одному на долг + один рост расходов (только сентябрь к августу).
        assert types == ["debt_overdue"] * 3 + ["spending_increased"]

    def test_purge_after_retention_keeps_idempotency(self, client, db_session, account):
        old = make_debt(client, "2026-10-01", counterparty_name="Погашен давно")
        alive = make_debt(client, "2026-09-01", counterparty_name="Всё ещё должен")
        check(client)
        notes = {n["message"].split("«")[1].split("»")[0]: n for n in listing(client)}
        # Пользователь удалил уведомление по долгу, который всё ещё актуален.
        client.delete(f"/api/v1/notifications/{notes['Всё ещё должен']['id']}")
        client.post(f"/api/v1/debts/{old['id']}/payments", json={"amount_minor": 1_000_000, "paid_at": "2026-10-15T09:00:00Z"})
        check(client)

        long_ago = datetime.now(timezone.utc) - timedelta(days=91)
        for n in db_session.query(Notification).all():
            n.created_at = long_ago
            if n.resolved_at is not None:
                n.resolved_at = long_ago
        db_session.commit()

        result = check(client)
        assert result["purged"] == 1  # неактуальное старше 90 дней
        assert result["created"] == 0  # удалённое, но актуальное не вернулось
        assert listing(client) == []
        assert db_session.query(Notification).count() == 1
        _ = alive

    def test_concurrent_check_is_rejected_not_duplicated(self, client):
        make_debt(client, "2026-10-01")
        assert service._LOCK.acquire(blocking=False)
        try:
            import app.api.v1.notifications as api

            original = api.generate_notifications
            api.generate_notifications = lambda db: original(db, wait_seconds=0)
            try:
                r = client.post("/api/v1/notifications/check")
            finally:
                api.generate_notifications = original
            assert r.status_code == 409
        finally:
            service._LOCK.release()
        assert check(client)["created"] == 1
        assert check(client)["created"] == 0

    def test_system_notification_is_one_off(self, client, db_session):
        assert service.create_system_notification(db_session, "test:1", "Системное", "Текст") is not None
        assert service.create_system_notification(db_session, "test:1", "Системное", "Текст") is None
        [n] = listing(client)
        assert (n["type"], n["entity_type"], n["entity_exists"]) == ("system", None, False)
        assert check(client)["resolved"] == 0  # системные engine не закрывает
