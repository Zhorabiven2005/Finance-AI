"""Финансовые предупреждения (Stage 3E): бюджеты, крупные расходы, рост
категорий, просроченные цели, отсутствие повторов и побочных эффектов.

Синтетические данные, in-memory БД (tests/conftest.py). Дата «сегодня» и
момент «сейчас» фиксированы, поэтому тесты не зависят от реальных часов.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import func, select

from app import clock
from app.db.models import Budget, Goal, GoalEntry, Notification, Transaction, Transfer
from app.insights.warnings import build_warnings
from tests.test_insights_api import Book

TODAY = date(2026, 10, 15)
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fixed_dates(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    monkeypatch.setattr(clock, "utc_today", lambda: TODAY)


def warnings(db, today=TODAY, now=NOW):
    return build_warnings(db, today=today, today_utc=today, now=now)


def of_type(out, kind):
    return [w for w in out.warnings if w.type == kind]


def budget(b, category, limit, year=2026, month=10):
    r = b.c.post("/api/v1/budgets", json={"category_id": b.cats[("expense", category)], "amount_minor": limit, "currency": "RUB", "year": year, "month": month})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --- A. бюджеты ------------------------------------------------------------------------------


class TestBudgets:
    def test_exceeded_is_fact_and_excludes_pace(self, seeded_client, db_session):
        b = Book(seeded_client)
        a = b.account()
        bid = budget(b, "Продукты", 1_000_000)
        for d in (2, 5, 9):
            b.tx(a, 400_000, f"2026-10-{d:02d}T09:00:00Z", "Продукты")
        out = warnings(db_session)
        (w,) = of_type(out, "budget_exceeded")
        assert w.key == f"budget_exceeded:{bid}:2026-10" and w.kind == "fact" and w.severity == "warning"
        assert "больше на 2 000,00 ₽" in w.message and w.period.label == "октябрь 2026"
        assert of_type(out, "budget_pace_risk") == []  # для того же бюджета — только факт

    def test_no_budget_no_warning(self, seeded_client, db_session):
        b = Book(seeded_client)
        a = b.account()
        b.tx(a, 900_000, "2026-10-05T09:00:00Z", "Продукты")
        out = warnings(db_session)
        assert of_type(out, "budget_exceeded") == of_type(out, "budget_pace_risk") == []
        assert not any("бюджет" in x.lower() for x in out.limitations)

    def test_pace_risk_mid_month_is_estimate(self, seeded_client, db_session):
        b = Book(seeded_client)
        a = b.account()
        bid = budget(b, "Кафе и рестораны", 1_000_000)
        for d in (3, 8, 12):
            b.tx(a, 200_000, f"2026-10-{d:02d}T09:00:00Z", "Кафе и рестораны")
        (w,) = of_type(warnings(db_session), "budget_pace_risk")
        # 6 000 за 15 дней → 6 000 × 31 / 15 = 12 400 > 10 000
        assert w.key == f"budget_pace_risk:{bid}:2026-10" and w.kind == "estimate" and w.severity == "attention"
        assert "около 12 400,00 ₽" in w.message and "оценка по темпу, а не факт" in w.message
        assert "можно потратить ещё 4 000,00 ₽" in w.recommendation

    def test_no_pace_at_month_start(self, seeded_client, db_session):
        b = Book(seeded_client)
        a = b.account()
        budget(b, "Кафе и рестораны", 1_000_000)
        for d in (1, 2, 3):
            b.tx(a, 300_000, f"2026-10-{d:02d}T09:00:00Z", "Кафе и рестораны")
        out = warnings(db_session, today=date(2026, 10, 4), now=datetime(2026, 10, 4, 12, tzinfo=timezone.utc))
        assert of_type(out, "budget_pace_risk") == []
        assert any("с 7-го числа" in x for x in out.limitations)

    def test_no_pace_with_too_few_operations(self, seeded_client, db_session):
        b = Book(seeded_client)
        a = b.account()
        budget(b, "Одежда и обувь", 1_000_000)
        b.tx(a, 800_000, "2026-10-02T09:00:00Z", "Одежда и обувь")  # одна покупка — не темп
        out = warnings(db_session)
        assert of_type(out, "budget_pace_risk") == []
        assert any("меньше 3 операций" in x for x in out.limitations)

    def test_within_pace_no_warning(self, seeded_client, db_session):
        b = Book(seeded_client)
        a = b.account()
        budget(b, "Транспорт", 1_000_000)
        for d in (3, 8, 12):
            b.tx(a, 100_000, f"2026-10-{d:02d}T09:00:00Z", "Транспорт")
        assert of_type(warnings(db_session), "budget_pace_risk") == []


# --- B. крупные расходы ----------------------------------------------------------------------


def usual_spending(b, a, n=24):
    for i in range(n):
        b.tx(a, 50_000, f"2026-{7 + i % 3:02d}-{i + 1:02d}T09:00:00Z", "Продукты")


class TestLargeExpenses:
    def test_one_warning_per_operation_and_stable_on_repeat(self, seeded_client, db_session):
        b = Book(seeded_client)
        a = b.account()
        usual_spending(b, a)
        tx_id = b.tx(a, 2_000_000, "2026-10-10T09:00:00Z", "Одежда и обувь")
        first, second = warnings(db_session), warnings(db_session)
        (w,) = of_type(first, "large_expense")
        assert w.key == f"large_expense:{tx_id}" and w.kind == "observation"
        assert "в 40,0 раза больше вашей обычной траты" in w.message and "не означает ошибку" in w.message
        assert [x.key for x in first.warnings] == [x.key for x in second.warnings]
        assert len({x.key for x in first.warnings}) == len(first.warnings)
        # сводка для интерфейса: те же операции, сумма в одной валюте
        (group,) = first.large_expense_groups
        assert (group.currency, group.count, group.total.minor, group.keys) == ("RUB", 1, 2_000_000, [w.key])

    def test_group_total_and_currencies_not_mixed(self, seeded_client, db_session):
        b = Book(seeded_client)
        rub, usd = b.account("Рубли"), b.account("Доллары", "USD")
        usual_spending(b, rub)
        for i in range(24):
            b.tx(usd, 1_000, f"2026-{7 + i % 3:02d}-{i + 1:02d}T09:00:00Z", "Продукты")
        b.tx(rub, 2_000_000, "2026-10-10T09:00:00Z", "Одежда и обувь")
        b.tx(rub, 3_000_000, "2026-10-11T09:00:00Z", "Жильё")
        b.tx(usd, 90_000, "2026-10-12T09:00:00Z", "Путешествия")
        out = warnings(db_session)
        groups = {g.currency: g for g in out.large_expense_groups}
        assert (groups["RUB"].count, groups["RUB"].total.minor) == (2, 5_000_000)
        assert (groups["USD"].count, groups["USD"].total.currency) == (1, "USD")
        assert sorted(k for g in out.large_expense_groups for k in g.keys) == sorted(w.key for w in of_type(out, "large_expense"))

    def test_no_group_without_large_expenses(self, seeded_client, db_session):
        b = Book(seeded_client)
        usual_spending(b, b.account())
        assert warnings(db_session).large_expense_groups == []

    def test_old_large_expense_is_not_repeated(self, seeded_client, db_session):
        b = Book(seeded_client)
        a = b.account()
        usual_spending(b, a)
        b.tx(a, 2_000_000, "2026-09-10T09:00:00Z", "Одежда и обувь")  # больше 30 дней назад
        assert of_type(warnings(db_session), "large_expense") == []

    def test_debt_repayments_are_not_living_expenses(self, seeded_client, db_session):
        b = Book(seeded_client)
        a = b.account(initial=100_000_000)
        usual_spending(b, a)
        debt = seeded_client.post("/api/v1/debts", json={"counterparty_name": "Кредит", "direction": "i_owe", "principal_minor": 3_000_000, "currency": "RUB"}).json()
        seeded_client.post(f"/api/v1/debts/{debt['id']}/payments", json={"amount_minor": 3_000_000, "paid_at": "2026-10-10T09:00:00Z", "account_id": a})
        b.tx(a, 2_500_000, "2026-10-11T09:00:00Z", "Погашение долга")
        assert of_type(warnings(db_session), "large_expense") == []

    def test_insufficient_baseline(self, seeded_client, db_session):
        b = Book(seeded_client)
        a = b.account()
        b.tx(a, 2_000_000, "2026-10-10T09:00:00Z")
        out = warnings(db_session)
        assert of_type(out, "large_expense") == []
        assert any("Крупные расходы в RUB не проверялись" in x for x in out.limitations)


# --- C. рост расходов по категории ----------------------------------------------------------------


def base_history(b, a):
    b.tx(a, 100, "2026-01-05T09:00:00Z", "Транспорт")  # история покрывает оба периода


class TestCategorySpike:
    def setup_september(self, b, a):
        base_history(b, a)
        for cat in ("Продукты", "Кафе и рестораны", "Транспорт"):
            b.tx(a, 1_000_000, "2026-09-05T09:00:00Z", cat)

    def test_reliable_spike(self, seeded_client, db_session):
        b = Book(seeded_client)
        a = b.account()
        self.setup_september(b, a)
        b.tx(a, 2_500_000, "2026-10-05T09:00:00Z", "Продукты")  # +150%, +15 000 при базе 30 000
        b.tx(a, 1_100_000, "2026-10-05T09:00:00Z", "Кафе и рестораны")  # +10% — не повод
        (w,) = of_type(warnings(db_session), "category_spike")
        assert w.key.startswith("category_spike:RUB:") and w.key.endswith(":2026-10-01")
        assert "Продукты" in w.title and "(+150,0%)" in w.message
        assert w.period.label == "1–15 октября 2026 против 1–15 сентября 2026"

    def test_no_history_no_spike(self, seeded_client, db_session):
        b = Book(seeded_client)
        a = b.account()
        b.tx(a, 1_000_000, "2026-09-10T09:00:00Z", "Продукты")  # история начинается внутри прошлого периода
        b.tx(a, 3_000_000, "2026-10-05T09:00:00Z", "Продукты")
        out = warnings(db_session)
        assert of_type(out, "category_spike") == []
        assert any("нет полных данных" in x for x in out.limitations)

    def test_zero_base_is_not_spike(self, seeded_client, db_session):
        b = Book(seeded_client)
        a = b.account()
        self.setup_september(b, a)
        b.tx(a, 5_000_000, "2026-10-05T09:00:00Z", "Путешествия")  # не было — нет базы
        assert of_type(warnings(db_session), "category_spike") == []

    def test_tiny_base_is_not_spike(self, seeded_client, db_session):
        b = Book(seeded_client)
        a = b.account()
        self.setup_september(b, a)
        b.tx(a, 50_000, "2026-09-06T09:00:00Z", "Связь и интернет")  # 500 ₽ — 1,6% базы
        b.tx(a, 400_000, "2026-10-06T09:00:00Z", "Связь и интернет")  # «+700%», но прирост мал
        assert of_type(warnings(db_session), "category_spike") == []

    def test_high_other_share_blocks_spikes(self, seeded_client, db_session):
        b = Book(seeded_client)
        a = b.account()
        self.setup_september(b, a)
        b.tx(a, 2_000_000, "2026-09-07T09:00:00Z", "Прочие расходы")
        b.tx(a, 3_000_000, "2026-10-05T09:00:00Z", "Продукты")
        out = warnings(db_session)
        assert of_type(out, "category_spike") == []
        assert any("Прочие расходы" in x and "недостоверны" in x for x in out.limitations)

    def test_too_early_in_month(self, seeded_client, db_session):
        b = Book(seeded_client)
        a = b.account()
        self.setup_september(b, a)
        b.tx(a, 3_000_000, "2026-10-02T09:00:00Z", "Продукты")
        out = warnings(db_session, today=date(2026, 10, 3), now=datetime(2026, 10, 3, 12, tzinfo=timezone.utc))
        assert of_type(out, "category_spike") == []
        assert any("с 7-го числа" in x for x in out.limitations)

    def test_internal_transfers_do_not_count(self, seeded_client, db_session):
        b = Book(seeded_client)
        a, s = b.account("Карта"), b.account("Сбережения")
        self.setup_september(b, a)
        b.transfer(a, s, 10_000_000, "2026-10-05T09:00:00Z")
        assert of_type(warnings(db_session), "category_spike") == []


# --- D. цели ------------------------------------------------------------------------------------


class TestGoals:
    def goal(self, c, name, target, target_date=None, saved=0):
        g = c.post("/api/v1/goals", json={"name": name, "target_amount_minor": target, "currency": "RUB", "target_date": target_date}).json()
        if saved:
            c.post(f"/api/v1/goals/{g['id']}/entries", json={"type": "contribution", "amount_minor": saved, "occurred_at": "2026-05-01T09:00:00Z"})
        return g["id"]

    def test_overdue_completed_and_without_date(self, seeded_client, db_session):
        c = seeded_client
        overdue = self.goal(c, "Отпуск", 10_000_000, "2026-09-01", saved=4_000_000)
        self.goal(c, "Ноутбук", 5_000_000, "2026-08-01", saved=5_000_000)  # выполнена — не просрочена
        self.goal(c, "Машина", 50_000_000)  # без срока
        self.goal(c, "Дом", 90_000_000, "2027-12-01")  # срок впереди
        out = warnings(db_session)
        (w,) = of_type(out, "goal_overdue")
        assert w.key == f"goal_overdue:{overdue}:2026-09-01" and w.kind == "fact"
        assert "Срок был 01.09.2026 (44 дн. назад)" in w.message and "(40,0%)" in w.message
        assert any("без срока: 1" in x for x in out.limitations)

    def test_goals_are_not_modified(self, seeded_client, db_session):
        self.goal(seeded_client, "Отпуск", 10_000_000, "2026-09-01", saved=1_000_000)
        before = [(g.id, g.target_date, g.is_archived) for g in db_session.scalars(select(Goal))]
        entries = db_session.scalar(select(func.count()).select_from(GoalEntry))
        warnings(db_session)
        assert [(g.id, g.target_date, g.is_archived) for g in db_session.scalars(select(Goal))] == before
        assert db_session.scalar(select(func.count()).select_from(GoalEntry)) == entries


# --- общие свойства ----------------------------------------------------------------------------


class TestGeneral:
    def test_empty(self, seeded_client, db_session):
        out = warnings(db_session)
        assert out.warnings == []

    def test_order_and_unique_keys(self, seeded_client, db_session):
        b = Book(seeded_client)
        a = b.account()
        usual_spending(b, a)
        budget(b, "Продукты", 100_000)
        b.tx(a, 200_000, "2026-10-03T09:00:00Z", "Продукты")  # бюджет превышен
        b.tx(a, 2_000_000, "2026-10-10T09:00:00Z", "Одежда и обувь")
        TestGoals().goal(seeded_client, "Отпуск", 10_000_000, "2026-09-01")
        out = warnings(db_session)
        assert [w.type for w in out.warnings][:2] == ["budget_exceeded", "goal_overdue"]
        assert len({w.key for w in out.warnings}) == len(out.warnings)

    def test_api_read_only_and_no_records(self, seeded_client, db_session):
        b = Book(seeded_client)
        a = b.account()
        usual_spending(b, a)
        budget(b, "Продукты", 100_000)
        models = (Transaction, Transfer, Notification, Goal, GoalEntry, Budget)
        before = [db_session.scalar(select(func.count()).select_from(m)) for m in models]
        r1 = seeded_client.get("/api/v1/insights/warnings")
        r2 = seeded_client.get("/api/v1/insights/warnings")
        assert r1.status_code == r2.status_code == 200
        assert [w["key"] for w in r1.json()["warnings"]] == [w["key"] for w in r2.json()["warnings"]]
        assert [db_session.scalar(select(func.count()).select_from(m)) for m in models] == before

    def test_untrusted_labels(self, seeded_client, db_session):
        b = Book(seeded_client)
        evil = b.category("Кафе‮<script>")
        a = b.account()
        r = b.c.post("/api/v1/budgets", json={"category_id": evil, "amount_minor": 100, "currency": "RUB", "year": 2026, "month": 10})
        assert r.status_code == 201
        b.tx(a, 1_000, "2026-10-02T09:00:00Z", evil, comment="SECRET-COMMENT")
        raw = seeded_client.get("/api/v1/insights/warnings").text
        assert "‮" not in raw and "SECRET-COMMENT" not in raw
