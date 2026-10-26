"""Ручная классификация операций (Stage 3F): назначение операции и единые
правила учёта во всех расчётах.

Синтетические данные, in-memory БД (tests/conftest.py). Миграция проверяется
на отдельном временном файле SQLite — основная БД не используется.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app import clock
from app.config import settings
from app.db.models import Transaction
from app.engine.flows import flow_kind
from app.insights.warnings import build_warnings
from tests.test_insights_api import Book

TODAY = date(2026, 10, 25)
BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def fixed_dates(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    monkeypatch.setattr(clock, "utc_today", lambda: TODAY)


def classify(c, tx_id, purpose, **extra):
    return c.patch(f"/api/v1/transactions/{tx_id}/purpose", json={"purpose": purpose, **extra})


def ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def analytics(c, date_from="2026-10-01T00:00:00Z", date_to="2026-10-31T23:59:59Z"):
    return ok(c.get("/api/v1/analytics", params={"date_from": date_from, "date_to": date_to}))


def insights(c, period="current_month"):
    return ok(c.get("/api/v1/insights", params={"period": period}))


def cash_flow(c):
    return next(i for i in insights(c)["insights"] if i["id"] == "cash_flow:RUB")


def metric(insight, label):
    found = [m for m in insight["metrics"] if m["label"] == label]
    return found[0]["money"]["minor"] if found else None


def comparison_rub(c):
    return next(x for x in insights(c)["comparison"]["by_currency"] if x["currency"] == "RUB")


def balance(c, account_id):
    return ok(c.get(f"/api/v1/accounts/{account_id}"))["balance"]["minor"]


@pytest.fixture()
def book(seeded_client):
    b = Book(seeded_client)
    b.main = b.account("Т-банк", initial=10_000_000)
    b.second = b.account("Сбербанк", initial=1_000_000)
    b.tx(b.main, 100, "2026-01-05T09:00:00Z", "Транспорт")  # история покрывает прошлый период
    return b


# --- 1–4. Виды операций ----------------------------------------------------------------------


class TestKinds:
    def test_regular_expense_stays_expense(self, book):
        tx = book.tx(book.main, 300_000, "2026-10-05T10:00:00Z", "Продукты")
        assert analytics(book.c)["summary"]["expense"]["minor"] == 300_000
        assert metric(cash_flow(book.c), "Расходы") == 300_000
        got = ok(book.c.get(f"/api/v1/transactions/{tx}"))
        assert got["purpose"] is None

    def test_own_transfer_is_neither_income_nor_expense(self, book):
        out = book.tx(book.main, 500_000, "2026-10-05T10:00:00Z", "Прочие расходы", comment="Перевод себе")
        inc = book.tx(book.second, 500_000, "2026-10-05T10:01:00Z", "Прочие доходы", "income")
        before = (balance(book.c, book.main), balance(book.c, book.second))
        ok(classify(book.c, out, "own_transfer", purpose_account_id=book.second))
        ok(classify(book.c, inc, "own_transfer", purpose_account_id=book.main))
        s = analytics(book.c)["summary"]
        assert (s["income"]["minor"], s["expense"]["minor"]) == (0, 0)
        cf = cash_flow(book.c)
        assert (metric(cf, "Доходы"), metric(cf, "Расходы")) == (0, 0)
        marked = next(i for i in cf["items"] if i["label"] == "Отмечены вами как переводы")
        assert marked["money"]["minor"] == 1_000_000 and marked["note"].startswith("2 шт.")
        # остатки счетов не меняются: деньги действительно переместились
        assert (balance(book.c, book.main), balance(book.c, book.second)) == before

    def test_external_product_transfer_excluded_but_visible(self, book):
        tx = book.tx(book.main, 1_808_906, "2026-10-05T10:19:00Z", "Прочие расходы", comment="Внутренний перевод на договор")
        ok(classify(book.c, tx, "external_transfer"))
        assert analytics(book.c)["summary"]["expense"]["minor"] == 0
        cf = cash_flow(book.c)
        assert metric(cf, "Расходы") == 0
        # изменение остатка по-прежнему учитывает ушедшие деньги
        assert metric(cf, "Изменение остатка на активных счетах") == -1_808_906
        listed = ok(book.c.get("/api/v1/transactions"))
        row = next(t for t in listed if t["id"] == tx)
        assert row["purpose"] == "external_transfer" and row["amount"]["minor"] == 1_808_906
        assert row["comment"] == "Внутренний перевод на договор"

    def test_debt_repayment_not_in_living_expenses(self, book):
        tx = book.tx(book.main, 2_000_000, "2026-10-10T10:00:00Z", "Прочие расходы")
        book.tx(book.main, 300_000, "2026-10-11T10:00:00Z", "Продукты")
        ok(classify(book.c, tx, "debt_repayment"))
        cf = cash_flow(book.c)
        assert metric(cf, "Расходы") == 2_300_000  # денежный поток: все расходы
        assert metric(cf, "Расходы на жизнь (без погашений долгов)") == 300_000
        structure = next(i for i in insights(book.c)["insights"] if i["id"] == "spending_structure:RUB")
        assert [x["label"] for x in structure["items"]] == ["Продукты"]
        r = comparison_rub(book.c)
        assert r["expense_without_debt_repayments"]["current"]["minor"] == 300_000
        assert r["debt_repayments"]["current"]["minor"] == 2_000_000


# --- 5. Кредитка: покупка и погашение --------------------------------------------------------


class TestCreditCard:
    def test_purchase_and_marked_repayment_not_double(self, book):
        book.tx(book.main, 3_000_000, "2026-10-03T10:00:00Z", "Одежда и обувь")  # покупка по кредитке
        repay = book.tx(book.main, 3_000_000, "2026-10-20T10:00:00Z", "Прочие расходы", comment="Погашение кредитки")
        assert comparison_rub(book.c)["expense_without_debt_repayments"]["current"]["minor"] == 6_000_000  # до отметки — дважды
        ok(classify(book.c, repay, "debt_repayment"))
        r = comparison_rub(book.c)
        assert r["expense_without_debt_repayments"]["current"]["minor"] == 3_000_000
        assert r["expense"]["current"]["minor"] == 6_000_000  # все расходы с погашением — честно
        # неопределённость названа, а не «двойного учёта нет»
        assert any("не может проверить" in w for w in r["warnings"])

    def test_linked_debt(self, book):
        debt = book.c.post("/api/v1/debts", json={"counterparty_name": "Кредитка", "direction": "i_owe", "principal_minor": 5_000_000, "currency": "RUB"}).json()
        tx = book.tx(book.main, 1_000_000, "2026-10-20T10:00:00Z", "Прочие расходы")
        out = ok(classify(book.c, tx, "debt_repayment", purpose_debt_id=debt["id"]))
        assert out["purpose_debt_id"] == debt["id"]
        # остаток долга не меняется: отметка — учёт, а не платёж по долгу
        assert ok(book.c.get(f"/api/v1/debts/{debt['id']}"))["remaining"]["minor"] == 5_000_000
        # удаление долга снимает ссылку, но не трогает операцию
        assert book.c.delete(f"/api/v1/debts/{debt['id']}").status_code == 204
        after = ok(book.c.get(f"/api/v1/transactions/{tx}"))
        assert (after["purpose"], after["purpose_debt_id"], after["amount"]["minor"]) == ("debt_repayment", None, 1_000_000)


# --- 6–8. Сохранение, отмена, никаких автоматических изменений ------------------------------------


class TestLifecycle:
    def test_persisted_and_survives_backup(self, book):
        tx = book.tx(book.main, 700_000, "2026-10-05T10:00:00Z", "Прочие расходы")
        ok(classify(book.c, tx, "external_transfer"))
        assert ok(book.c.get(f"/api/v1/transactions/{tx}"))["purpose"] == "external_transfer"
        exported = book.c.get("/api/v1/export/backup").content
        doc = json.loads(exported)
        assert doc["version"] == 3
        assert next(t for t in doc["data"]["transactions"] if t["id"] == tx)["purpose"] == "external_transfer"
        assert book.c.post("/api/v1/import/backup/restore?confirm=true", content=exported).status_code == 200
        assert ok(book.c.get(f"/api/v1/transactions/{tx}"))["purpose"] == "external_transfer"

    def test_change_and_undo(self, book):
        tx = book.tx(book.main, 400_000, "2026-10-05T10:00:00Z", "Прочие расходы")
        ok(classify(book.c, tx, "own_transfer", purpose_account_id=book.second))
        assert analytics(book.c)["summary"]["expense"]["minor"] == 0
        ok(classify(book.c, tx, "debt_repayment"))
        assert analytics(book.c)["summary"]["expense"]["minor"] == 400_000  # погашение — в «всех расходах»
        assert metric(cash_flow(book.c), "Расходы на жизнь (без погашений долгов)") == 0
        out = ok(classify(book.c, tx, None))
        assert (out["purpose"], out["purpose_account_id"], out["purpose_debt_id"]) == (None, None, None)
        assert metric(cash_flow(book.c), "Расходы") == 400_000
        assert metric(cash_flow(book.c), "Расходы на жизнь (без погашений долгов)") is None

    def test_nothing_is_classified_automatically(self, book, db_session):
        a = book.tx(book.main, 900_000, "2026-10-05T10:00:00Z", "Прочие расходы", comment="Внутренний перевод на договор")
        b = book.tx(book.second, 900_000, "2026-10-05T10:00:00Z", "Прочие доходы", "income", comment="Перевод себе")
        insights(book.c)
        book.c.get("/api/v1/insights/warnings")
        cands = ok(book.c.get(f"/api/v1/transactions/{a}/pair-candidates"))
        assert [x["id"] for x in cands] == [b]  # подсказка, а не связь
        assert db_session.scalar(select(func.count()).select_from(Transaction).where(Transaction.purpose.is_not(None))) == 0

    def test_pair_candidates_exclude_marked_and_other_amounts(self, book):
        a = book.tx(book.main, 900_000, "2026-10-05T10:00:00Z", "Прочие расходы")
        b = book.tx(book.second, 900_000, "2026-10-05T12:00:00Z", "Прочие доходы", "income")
        book.tx(book.second, 900_001, "2026-10-05T12:00:00Z", "Прочие доходы", "income")
        book.tx(book.second, 900_000, "2026-10-09T12:00:00Z", "Прочие доходы", "income")  # дальше суток
        ok(classify(book.c, b, "own_transfer", purpose_account_id=book.main))
        assert ok(book.c.get(f"/api/v1/transactions/{a}/pair-candidates")) == []


# --- валидация -------------------------------------------------------------------------------------


class TestValidation:
    def test_rules(self, book):
        exp = book.tx(book.main, 100_000, "2026-10-05T10:00:00Z", "Прочие расходы")
        inc = book.tx(book.main, 100_000, "2026-10-05T10:00:00Z", "Прочие доходы", "income")
        usd = book.account("Доллары", "USD")
        assert classify(book.c, exp, "own_transfer").status_code == 422  # нет второго счёта
        assert classify(book.c, exp, "own_transfer", purpose_account_id=book.main).status_code == 422
        assert classify(book.c, exp, "own_transfer", purpose_account_id=usd).status_code == 422
        assert classify(book.c, exp, "external_transfer", purpose_account_id=book.second).status_code == 422
        assert classify(book.c, inc, "debt_repayment").status_code == 422  # доход не погашение
        owed = book.c.post("/api/v1/debts", json={"counterparty_name": "Друг", "direction": "owed_to_me", "principal_minor": 100, "currency": "RUB"}).json()
        assert classify(book.c, exp, "debt_repayment", purpose_debt_id=owed["id"]).status_code == 422
        assert classify(book.c, exp, "bogus").status_code == 422
        assert classify(book.c, 999_999, None).status_code == 404

    def test_debt_ledger_operation_is_managed_by_debt(self, book):
        debt = book.c.post("/api/v1/debts", json={"counterparty_name": "Банк", "direction": "i_owe", "principal_minor": 500_000, "currency": "RUB"}).json()
        book.c.post(f"/api/v1/debts/{debt['id']}/payments", json={"amount_minor": 100_000, "paid_at": "2026-10-05T10:00:00Z", "account_id": book.main})
        ledger = next(t for t in ok(book.c.get("/api/v1/transactions")) if t["debt_id"] == debt["id"])
        assert classify(book.c, ledger["id"], "external_transfer").status_code == 400

    def test_edit_conflicting_with_purpose_is_rejected(self, book):
        tx = book.tx(book.main, 100_000, "2026-10-05T10:00:00Z", "Прочие расходы")
        ok(classify(book.c, tx, "own_transfer", purpose_account_id=book.second))
        r = book.c.patch(f"/api/v1/transactions/{tx}", json={"account_id": book.second})
        assert r.status_code == 400 and "обычный тип" in r.json()["detail"]
        ok(classify(book.c, tx, "debt_repayment"))
        cat = book.cats[("income", "Прочие доходы")]
        r = book.c.patch(f"/api/v1/transactions/{tx}", json={"type": "income", "category_id": cat})
        assert r.status_code == 400
        assert ok(book.c.get(f"/api/v1/transactions/{tx}"))["type"] == "expense"  # ничего не поменялось


# --- 9. Одни правила во всех расчётах ---------------------------------------------------------------


class TestConsistency:
    def test_same_rules_everywhere(self, book, db_session):
        for i in range(24):  # обычный уровень трат
            book.tx(book.main, 50_000, f"2026-{7 + i % 3:02d}-{i + 1:02d}T09:00:00Z", "Продукты")
        transfer = book.tx(book.main, 2_000_000, "2026-10-12T10:00:00Z", "Прочие расходы")
        purchase = book.tx(book.main, 150_000, "2026-10-13T10:00:00Z", "Прочие расходы")
        budget = book.c.post("/api/v1/budgets", json={"category_id": book.cats[("expense", "Прочие расходы")], "amount_minor": 1_000_000, "currency": "RUB", "year": 2026, "month": 10}).json()

        def large_keys():
            out = build_warnings(db_session, today=TODAY, today_utc=TODAY, now=__import__("datetime").datetime(2026, 10, 25, 12, tzinfo=__import__("datetime").timezone.utc))
            return [w.key for w in out.warnings if w.type == "large_expense"]

        assert f"large_expense:{transfer}" in large_keys()
        ok(classify(book.c, transfer, "external_transfer"))

        assert analytics(book.c)["summary"]["expense"]["minor"] == 150_000
        dash = ok(book.c.get("/api/v1/dashboard"))
        other = next(x for x in dash["top_expenses"] if x["category_name"] == "Прочие расходы")
        assert other["amount"]["minor"] == 150_000
        assert ok(book.c.get(f"/api/v1/budgets/{budget['id']}"))["spent"]["minor"] == 150_000
        ctx = ok(book.c.get("/api/v1/context"))
        assert ctx["cash_flow"]["current_month"]["by_currency"][0]["expense"]["minor"] == 150_000
        assert metric(cash_flow(book.c), "Расходы") == 150_000
        r = comparison_rub(book.c)
        assert r["expense"]["current"]["minor"] == 150_000
        t = r["transfers_excluded"]
        assert (t["marked_current_count"], t["marked_current_total"]["minor"]) == (1, 2_000_000)
        # предупреждение о крупном расходе для перевода не появляется
        assert f"large_expense:{transfer}" not in large_keys()
        assert purchase  # обычная покупка осталась обычной
        assert ok(book.c.get(f"/api/v1/transactions/{purchase}"))["purpose"] is None


# --- 10–11. Доходы, возвраты и неизменность истории ----------------------------------------------


class TestUnchanged:
    def test_income_and_refunds_follow_existing_model(self, book):
        book.tx(book.main, 5_000_000, "2026-10-01T10:00:00Z", "Зарплата", "income")
        book.tx(book.main, 300_000, "2026-10-04T10:00:00Z", "Прочие доходы", "income", comment="Возврат покупки")
        assert analytics(book.c)["summary"]["income"]["minor"] == 5_300_000
        assert metric(cash_flow(book.c), "Доходы") == 5_300_000

    def test_classification_does_not_touch_history(self, book, db_session):
        tx = book.tx(book.main, 1_234_567, "2026-10-05T10:19:00Z", "Прочие расходы", comment="Внутренний перевод на договор")
        row = db_session.get(Transaction, tx)
        before = (row.account_id, row.category_id, row.type, row.amount_minor, row.currency, row.occurred_at, row.comment)
        for purpose, extra in (("external_transfer", {}), ("own_transfer", {"purpose_account_id": book.second}), ("debt_repayment", {}), (None, {})):
            ok(classify(book.c, tx, purpose, **extra))
            db_session.expire_all()
            row = db_session.get(Transaction, tx)
            assert (row.account_id, row.category_id, row.type, row.amount_minor, row.currency, row.occurred_at, row.comment) == before

    def test_flow_kind_rules(self):
        class T:
            def __init__(self, type, purpose=None, debt_payment_id=None, category_id=1):
                self.type, self.purpose, self.debt_payment_id, self.category_id = type, purpose, debt_payment_id, category_id

        assert flow_kind(T("expense")) == "expense"
        assert flow_kind(T("income")) == "income"
        assert flow_kind(T("expense", "own_transfer")) == flow_kind(T("income", "external_transfer")) == "transfer"
        assert flow_kind(T("expense", "debt_repayment")) == "debt_repayment"
        assert flow_kind(T("expense", debt_payment_id=5)) == "debt_repayment"
        assert flow_kind(T("expense", category_id=9), frozenset({9})) == "debt_repayment"
        assert flow_kind(T("income", debt_payment_id=5)) == "income"  # возврат долга мне — как и раньше


# --- 12. Миграция на временной копии -----------------------------------------------------------------


class TestMigration:
    def test_upgrade_keeps_old_rows_and_downgrade_works(self, tmp_path, monkeypatch):
        from alembic import command
        from alembic.config import Config

        db_file = tmp_path / "copy.db"
        assert db_file.resolve() != (BACKEND / "data" / "finance.db").resolve()
        monkeypatch.setattr(settings, "database_path", db_file)
        cfg = Config(str(BACKEND / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND / "alembic"))
        command.upgrade(cfg, "36106d4a5974")  # схема до Stage 3F

        con = sqlite3.connect(db_file)
        now = "2026-10-01 10:00:00.000000"
        con.execute("INSERT INTO accounts (id, name, type, currency, initial_balance_minor, is_active, created_at, updated_at) VALUES (1, 'Счёт', 'bank', 'RUB', 0, 1, ?, ?)", (now, now))
        con.execute("INSERT INTO categories (id, name, type, is_default, is_archived, created_at, updated_at) VALUES (1, 'Прочие расходы', 'expense', 1, 0, ?, ?)", (now, now))
        con.execute(
            "INSERT INTO transactions (id, account_id, category_id, type, amount_minor, currency, occurred_at, comment, created_at, updated_at) "
            "VALUES (7, 1, 1, 'expense', 1808906, 'RUB', ?, 'Внутренний перевод на договор', ?, ?)",
            (now, now, now),
        )
        con.commit()
        before = con.execute("SELECT * FROM transactions").fetchall()
        con.close()

        command.upgrade(cfg, "head")
        con = sqlite3.connect(db_file)
        cols = [r[1] for r in con.execute("PRAGMA table_info(transactions)")]
        assert cols[-3:] == ["purpose", "purpose_account_id", "purpose_debt_id"]
        rows = con.execute("SELECT * FROM transactions").fetchall()
        assert [r[: len(before[0])] for r in rows] == before and rows[0][-3:] == (None, None, None)
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        con.close()

        command.downgrade(cfg, "36106d4a5974")
        con = sqlite3.connect(db_file)
        assert con.execute("SELECT * FROM transactions").fetchall() == before
        con.close()


# --- 13. Основная БД не используется ------------------------------------------------------------------


def test_tests_never_use_main_db():
    assert settings.db_file.resolve() != (BACKEND / "data" / "finance.db").resolve()
