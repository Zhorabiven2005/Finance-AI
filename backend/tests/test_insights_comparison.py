"""Сравнение периодов (Stage 3D): правила окон и изменений, API и объяснение.

Синтетические данные, in-memory БД (tests/conftest.py), фейковый Ollama.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app import clock
from app.engine import comparison as cmp
from app.engine.money import Money
from tests.assistant_fakes import StreamRoute, chat_chunks, healthy_routes
from tests.test_insights_api import Book, explain, get

TODAY = date(2026, 10, 25)
RUB = lambda minor: Money.of(minor, "RUB")  # noqa: E731


@pytest.fixture(autouse=True)
def fixed_dates(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    monkeypatch.setattr(clock, "utc_today", lambda: TODAY)


# --- окна периодов -----------------------------------------------------------------------


class TestWindows:
    def test_incomplete_month_compares_same_days(self):
        w = cmp.comparison_windows("current_month", date(2026, 10, 25))
        assert (w.current.first, w.current.last) == (date(2026, 10, 1), date(2026, 10, 25))
        assert (w.previous.first, w.previous.last) == (date(2026, 9, 1), date(2026, 9, 25))
        assert w.same_days and not w.previous_shorter and w.current.days == w.previous.days == 25

    def test_previous_month_shorter(self):
        w = cmp.comparison_windows("current_month", date(2026, 3, 31))
        assert (w.previous.first, w.previous.last) == (date(2026, 2, 1), date(2026, 2, 28))
        assert w.previous_shorter

    def test_leap_february(self):
        w = cmp.comparison_windows("current_month", date(2028, 3, 30))
        assert w.previous.last == date(2028, 2, 29)

    def test_year_boundary(self):
        w = cmp.comparison_windows("current_month", date(2027, 1, 15))
        assert (w.previous.first, w.previous.last) == (date(2026, 12, 1), date(2026, 12, 15))
        p = cmp.comparison_windows("previous_month", date(2027, 1, 15))
        assert (p.current.first, p.current.last) == (date(2026, 12, 1), date(2026, 12, 31))
        assert (p.previous.first, p.previous.last) == (date(2026, 11, 1), date(2026, 11, 30))

    def test_three_months(self):
        w = cmp.comparison_windows("last_3_months", date(2027, 2, 10))
        assert (w.current.first, w.current.last) == (date(2026, 11, 1), date(2027, 1, 31))
        assert (w.previous.first, w.previous.last) == (date(2026, 8, 1), date(2026, 10, 31))
        assert not w.same_days

    def test_window_end_is_last_microsecond(self):
        w = cmp.Window(date(2026, 10, 1), date(2026, 10, 25))
        assert w.end == datetime(2026, 10, 26, tzinfo=timezone.utc) - timedelta(microseconds=1)


class TestChange:
    def test_growth_and_decline(self):
        up = cmp.change(RUB(15_000), RUB(10_000))
        assert up.delta == RUB(5_000) and up.percent == Decimal(50)
        down = cmp.change(RUB(7_500), RUB(10_000))
        assert down.delta == RUB(-2_500) and down.percent == Decimal(-25)

    def test_zero_base_has_no_percent(self):
        c = cmp.change(RUB(10_000), RUB(0))
        assert c.percent is None and c.percent_null_reason == "zero_base" and c.delta == RUB(10_000)

    def test_both_zero(self):
        c = cmp.change(RUB(0), RUB(0))
        assert c.delta == RUB(0) and c.percent is None

    def test_insufficient_history_hides_percent(self):
        c = cmp.change(RUB(15_000), RUB(10_000), history_ok=False)
        assert c.percent is None and c.percent_null_reason == "insufficient_history" and c.delta == RUB(5_000)


class TestMirrorPairs:
    def m(self, id, acc, kind, amount, day=date(2026, 10, 5)):
        return cmp.Movement(id, acc, kind, amount, day)

    def test_same_amount_same_day_different_accounts(self):
        pairs = cmp.mirror_pairs([self.m(1, 1, "expense", 500), self.m(2, 2, "income", 500)])
        assert [(a.id, b.id) for a, b in pairs] == [(1, 2)]

    def test_not_paired(self):
        assert cmp.mirror_pairs([self.m(1, 1, "expense", 500), self.m(2, 1, "income", 500)]) == []  # тот же счёт
        assert cmp.mirror_pairs([self.m(1, 1, "expense", 500), self.m(2, 2, "income", 501)]) == []
        assert cmp.mirror_pairs([self.m(1, 1, "expense", 500), self.m(2, 2, "income", 500, date(2026, 10, 6))]) == []

    def test_one_to_one(self):
        pairs = cmp.mirror_pairs([self.m(1, 1, "expense", 500), self.m(3, 1, "expense", 500), self.m(2, 2, "income", 500)])
        assert len(pairs) == 1


# --- API ------------------------------------------------------------------------------------


def comparison(c, period="current_month"):
    return get(c, period)["comparison"]


def rub_of(cc):
    return next(x for x in cc["by_currency"] if x["currency"] == "RUB")


def history(b, acc):
    """Операция задолго до сравниваемых периодов: история покрывает оба."""
    b.tx(acc, 100, "2026-01-05T09:00:00Z", "Транспорт")


class TestComparisonApi:
    def test_same_days_of_incomplete_month(self, seeded_client):
        b = Book(seeded_client)
        a = b.account()
        history(b, a)
        b.tx(a, 100_000, "2026-09-10T09:00:00Z", "Продукты")
        b.tx(a, 900_000, "2026-09-26T09:00:00Z", "Продукты")  # после 25-го — вне окна сравнения
        b.tx(a, 150_000, "2026-10-10T09:00:00Z", "Продукты")
        cc = comparison(seeded_client)
        assert cc["current"]["label"] == "1–25 октября 2026" and cc["previous"]["label"] == "1–25 сентября 2026"
        assert cc["same_days"] and "одинаковые дни" in cc["note"]
        r = rub_of(cc)
        assert r["expense"]["current"]["minor"] == 150_000 and r["expense"]["previous"]["minor"] == 100_000
        assert r["expense"]["delta"]["minor"] == 50_000 and r["expense"]["percent"] == 50.0
        assert r["confidence"] == "high" and "Расходы на жизнь выросли на 500,00 ₽ (+50,0%)" in r["summary"]

    def test_positive_and_negative_category_changes(self, seeded_client):
        b = Book(seeded_client)
        a = b.account()
        history(b, a)
        b.tx(a, 1_000_000, "2026-09-05T09:00:00Z", "Зарплата", "income")
        b.tx(a, 400_000, "2026-09-05T09:00:00Z", "Кафе и рестораны")
        b.tx(a, 100_000, "2026-09-06T09:00:00Z", "Продукты")
        b.tx(a, 800_000, "2026-10-05T09:00:00Z", "Зарплата", "income")
        b.tx(a, 100_000, "2026-10-05T09:00:00Z", "Кафе и рестораны")
        b.tx(a, 300_000, "2026-10-06T09:00:00Z", "Продукты")
        b.tx(a, 50_000, "2026-10-07T09:00:00Z", "Транспорт")
        r = rub_of(comparison(seeded_client))
        assert r["income"]["delta"]["minor"] == -200_000 and r["income"]["percent"] == -20.0
        assert r["net"]["current"]["minor"] == 350_000 and r["net"]["previous"]["minor"] == 500_000
        assert [x["label"] for x in r["categories_up"]] == ["Продукты", "Транспорт"]
        assert r["categories_up"][0]["percent"] == 200.0
        transport = r["categories_up"][1]
        assert transport["percent"] is None and transport["percent_null_reason"] == "zero_base"  # не было — нет «∞%»
        assert [x["label"] for x in r["categories_down"]] == ["Кафе и рестораны"]
        assert r["categories_down"][0]["percent"] == -75.0
        assert "Доходы снизились на 2 000,00 ₽ (-20,0%)" in r["summary"]
        assert "Сильнее всего выросли расходы на «Продукты»" in r["summary"]
        assert "Сильнее всего снизились на «Кафе и рестораны»" in r["summary"]

    def test_no_history_no_percent_and_no_claims(self, seeded_client):
        b = Book(seeded_client)
        a = b.account()
        b.tx(a, 150_000, "2026-10-10T09:00:00Z")
        r = rub_of(comparison(seeded_client))
        assert r["expense"]["percent"] is None and r["expense"]["percent_null_reason"] == "insufficient_history"
        assert r["confidence"] == "low"
        assert "выросли" not in r["summary"] and "Надёжно сравнить" in r["summary"]
        assert any("операций в приложении нет" in w for w in r["warnings"])

    def test_partially_covered_previous_period(self, seeded_client):
        b = Book(seeded_client)
        a = b.account()
        b.tx(a, 100_000, "2026-09-20T09:00:00Z")
        b.tx(a, 100_000, "2026-10-10T09:00:00Z")
        r = rub_of(comparison(seeded_client))
        assert r["confidence"] == "low" and r["expense"]["percent"] is None
        assert any("только с 20.09.2026" in w and "частично" in w for w in r["warnings"])

    def test_empty(self, seeded_client):
        cc = comparison(seeded_client)
        assert cc["by_currency"] == [] and "нет операций" in cc["unavailable_reason"]

    def test_previous_month_and_year_boundary(self, seeded_client, monkeypatch):
        monkeypatch.setattr(clock, "today", lambda: date(2027, 1, 10))
        b = Book(seeded_client)
        a = b.account()
        history(b, a)
        b.tx(a, 200_000, "2026-11-15T09:00:00Z")
        b.tx(a, 300_000, "2026-12-31T23:59:59Z")
        b.tx(a, 999_000, "2027-01-01T00:00:00Z")  # уже январь — не в декабре
        cc = comparison(seeded_client, "previous_month")
        assert (cc["current"]["label"], cc["previous"]["label"]) == ("декабрь 2026", "ноябрь 2026")
        r = rub_of(cc)
        assert (r["expense"]["current"]["minor"], r["expense"]["previous"]["minor"]) == (300_000, 200_000)

    def test_three_months(self, seeded_client):
        b = Book(seeded_client)
        a = b.account()
        history(b, a)
        b.tx(a, 100_000, "2026-04-15T09:00:00Z")
        b.tx(a, 100_000, "2026-08-15T09:00:00Z")
        b.tx(a, 100_000, "2026-09-15T09:00:00Z")
        b.tx(a, 500_000, "2026-10-01T09:00:00Z")  # текущий месяц не входит
        cc = comparison(seeded_client, "last_3_months")
        assert (cc["current"]["label"], cc["previous"]["label"]) == ("июль–сентябрь 2026", "апрель–июнь 2026")
        r = rub_of(cc)
        assert (r["expense"]["current"]["minor"], r["expense"]["previous"]["minor"], r["expense"]["percent"]) == (200_000, 100_000, 100.0)

    def test_currencies_separate(self, seeded_client):
        b = Book(seeded_client)
        rub, usd = b.account("Рубли"), b.account("Доллары", "USD")
        history(b, rub)
        b.tx(rub, 100_000, "2026-10-02T09:00:00Z")
        b.tx(usd, 5_000, "2026-10-02T09:00:00Z")
        cc = comparison(seeded_client)
        assert [x["currency"] for x in cc["by_currency"]] == ["RUB", "USD"]
        usd_cmp = cc["by_currency"][1]
        assert usd_cmp["expense"]["current"] == {"minor": 5_000, "currency": "USD"}


class TestTransfersAndCredit:
    def test_internal_transfers_are_excluded(self, seeded_client):
        b = Book(seeded_client)
        a, s = b.account("Карта"), b.account("Накопительный")
        history(b, a)
        b.tx(a, 100_000, "2026-10-02T09:00:00Z")
        b.transfer(a, s, 5_000_000, "2026-10-03T09:00:00Z")
        b.transfer(s, a, 1_000_000, "2026-09-03T09:00:00Z")
        r = rub_of(comparison(seeded_client))
        assert r["expense"]["current"]["minor"] == 100_000 and r["income"]["current"]["minor"] == 0
        assert r["income"]["previous"]["minor"] == 0
        t = r["transfers_excluded"]
        assert (t["current_count"], t["current_total"]["minor"], t["previous_count"], t["previous_total"]["minor"]) == (1, 5_000_000, 1, 1_000_000)

    def test_credit_card_as_account_no_double_count(self, seeded_client):
        """Кредитка как счёт: покупки — расходы по ней, погашение — перевод.
        Покупка учтена один раз, погашение в расходы не попадает."""
        b = Book(seeded_client)
        debit, card = b.account("Дебетовая"), b.account("Кредитка")
        history(b, debit)
        b.tx(card, 3_000_000, "2026-10-03T09:00:00Z", "Одежда и обувь")
        b.transfer(debit, card, 3_000_000, "2026-10-20T09:00:00Z")
        r = rub_of(comparison(seeded_client))
        assert r["expense"]["current"]["minor"] == 3_000_000
        assert r["debt_repayments"]["current"]["minor"] == 0 and r["possible_internal_pairs"]["count"] == 0

    def test_debt_repayment_shown_separately(self, seeded_client):
        """Кредитка как долг: погашение — расход модели. Если и покупки записаны
        расходами, двойной учёт виден: есть итог «без погашений» и предупреждение."""
        b = Book(seeded_client)
        a = b.account(initial=10_000_000)
        history(b, a)
        b.tx(a, 3_000_000, "2026-10-03T09:00:00Z", "Одежда и обувь")
        debt = seeded_client.post("/api/v1/debts", json={"counterparty_name": "Кредитка", "direction": "i_owe", "principal_minor": 3_000_000, "currency": "RUB"}).json()
        seeded_client.post(f"/api/v1/debts/{debt['id']}/payments", json={"amount_minor": 3_000_000, "paid_at": "2026-10-20T09:00:00Z", "account_id": a})
        b.tx(a, 50_000, "2026-10-21T09:00:00Z", "Погашение долга")  # вручную в категории долга
        r = rub_of(comparison(seeded_client))
        assert r["expense"]["current"]["minor"] == 6_050_000
        assert r["debt_repayments"]["current"]["minor"] == 3_050_000
        assert r["expense_without_debt_repayments"]["current"]["minor"] == 3_000_000
        assert any("не может проверить" in w for w in r["warnings"])
        assert r["confidence"] == "medium" and "Расходы на жизнь" in r["summary"]
        assert [c["label"] for c in r["categories"]] == ["Одежда и обувь"]

    def test_possible_unrecorded_transfer_is_flagged_not_excluded(self, seeded_client):
        b = Book(seeded_client)
        t, s = b.account("Т"), b.account("С")
        history(b, t)
        b.tx(t, 1_000_000, "2026-10-05T10:00:00Z", "Прочие расходы", comment="Перевод на карту")
        b.tx(s, 1_000_000, "2026-10-05T10:01:00Z", "Прочие доходы", "income")
        r = rub_of(comparison(seeded_client))
        assert r["possible_internal_pairs"] == {"count": 1, "total": {"minor": 1_000_000, "currency": "RUB"}}
        assert r["expense"]["current"]["minor"] == 1_000_000 and r["income"]["current"]["minor"] == 1_000_000
        assert r["confidence"] == "medium" and any("записанные как операции" in w for w in r["warnings"])


class TestReliability:
    def test_other_share_change(self, seeded_client):
        b = Book(seeded_client)
        a = b.account()
        history(b, a)
        b.tx(a, 100_000, "2026-09-05T09:00:00Z", "Продукты")
        b.tx(a, 300_000, "2026-10-05T09:00:00Z", "Прочие расходы")
        b.tx(a, 100_000, "2026-10-06T09:00:00Z", "Продукты")
        r = rub_of(comparison(seeded_client))
        assert r["other_share"] == {"current": 75.0, "previous": 0.0, "delta_points": 75.0}
        assert r["confidence"] == "medium" and any("менее достоверны" in w for w in r["warnings"])

    def test_large_expenses_use_one_threshold(self, seeded_client):
        b = Book(seeded_client)
        a = b.account()
        history(b, a)
        for i in range(24):
            b.tx(a, 50_000, f"2026-{7 + i % 3:02d}-{i + 1:02d}T09:00:00Z")
        b.tx(a, 2_000_000, "2026-09-12T09:00:00Z", "Жильё")
        b.tx(a, 3_000_000, "2026-10-12T09:00:00Z", "Жильё")
        b.tx(a, 2_500_000, "2026-10-13T09:00:00Z", "Жильё")
        le = rub_of(comparison(seeded_client))["large_expenses"]
        assert (le["current_count"], le["previous_count"]) == (2, 1)
        assert le["total"]["current"]["minor"] == 5_500_000 and le["total"]["percent"] == 175.0

    def test_large_expenses_insufficient(self, seeded_client):
        b = Book(seeded_client)
        a = b.account()
        b.tx(a, 100_000, "2026-10-05T09:00:00Z")
        r = rub_of(comparison(seeded_client))
        assert r["large_expenses"] is None and "Мало расходов" in r["large_expenses_null_reason"]


class TestComparisonExplain:
    def test_model_gets_comparison_facts_only(self, seeded_client):
        b = Book(seeded_client)
        a = b.account()
        history(b, a)
        b.tx(a, 100_000, "2026-09-05T09:00:00Z", "Продукты", comment="SECRET-COMMENT")
        b.tx(a, 150_000, "2026-10-05T09:00:00Z", "Продукты")
        routes = healthy_routes()
        routes["/api/chat"] = StreamRoute(chat_chunks("Расходы выросли на 500 ₽, это +50,0%."))
        events, bodies = explain(seeded_client, "comparison:RUB", routes)
        system = bodies[0]["messages"][0]["content"]
        assert "сравнение периодов" in system and "1–25 сентября 2026" in system
        assert "SECRET-COMMENT" not in json.dumps(bodies[0], ensure_ascii=False)
        assert '"Продукты"' in system.split("<<<ДАННЫЕ")[1]
        assert events[0]["insight_id"] == "comparison:RUB"
        assert events[-1]["type"] == "done" and events[-1]["grounding"]["unverified"] == []

    def test_unknown_currency(self, seeded_client):
        b = Book(seeded_client)
        b.tx(b.account(), 100, "2026-10-05T09:00:00Z")
        r = seeded_client.post("/api/v1/insights/explain", json={"insight_id": "comparison:USD"})
        assert r.status_code == 404


# --- финальная проверка: переводы и кредитки в обоих периодах ------------------------------


class TestCreditCardLogicBothPeriods:
    """Регрессия: логика переводов и погашений одинакова в текущем и прошлом
    периоде; основной показатель «расходы на жизнь» не растёт от погашения."""

    def card_debt(self, c, account, amount, paid_at):
        debt = c.post("/api/v1/debts", json={"counterparty_name": "Кредитная карта", "direction": "i_owe", "principal_minor": amount, "currency": "RUB"}).json()
        r = c.post(f"/api/v1/debts/{debt['id']}/payments", json={"amount_minor": amount, "paid_at": paid_at, "account_id": account})
        assert r.status_code == 201, r.text

    def test_own_transfers_change_nothing_in_both_periods(self, seeded_client):
        b = Book(seeded_client)
        a, s = b.account("Карта"), b.account("Сбережения")
        history(b, a)
        b.tx(a, 10_000, "2026-09-05T09:00:00Z", "Продукты")
        b.tx(a, 20_000, "2026-10-05T09:00:00Z", "Продукты")
        b.transfer(a, s, 2_000_000, "2026-09-10T09:00:00Z")
        b.transfer(s, a, 700_000, "2026-10-10T09:00:00Z")
        r = rub_of(comparison(seeded_client))
        assert (r["income"]["current"]["minor"], r["income"]["previous"]["minor"]) == (0, 0)
        for key in ("expense", "expense_without_debt_repayments"):
            assert (r[key]["current"]["minor"], r[key]["previous"]["minor"]) == (20_000, 10_000), key
        assert [c["label"] for c in r["categories"]] == ["Продукты"]
        t = r["transfers_excluded"]
        assert (t["current_count"], t["current_total"]["minor"], t["previous_count"], t["previous_total"]["minor"]) == (1, 700_000, 1, 2_000_000)

    def test_only_transfers_is_nothing_to_compare(self, seeded_client):
        b = Book(seeded_client)
        a, s = b.account("Карта"), b.account("Сбережения")
        b.transfer(a, s, 2_000_000, "2026-09-10T09:00:00Z")
        b.transfer(s, a, 700_000, "2026-10-10T09:00:00Z")
        cc = comparison(seeded_client)
        assert cc["by_currency"] == [] and "нет операций" in cc["unavailable_reason"]

    def test_card_account_purchase_counted_once_in_both_periods(self, seeded_client):
        b = Book(seeded_client)
        debit, card = b.account("Дебетовая"), b.account("Кредитка")
        history(b, debit)
        b.tx(card, 1_000_000, "2026-09-03T09:00:00Z", "Одежда и обувь")
        b.transfer(debit, card, 1_000_000, "2026-09-20T09:00:00Z")
        b.tx(card, 400_000, "2026-10-03T09:00:00Z", "Одежда и обувь")
        b.transfer(debit, card, 400_000, "2026-10-20T09:00:00Z")
        r = rub_of(comparison(seeded_client))
        assert (r["expense"]["current"]["minor"], r["expense"]["previous"]["minor"]) == (400_000, 1_000_000)
        assert (r["expense_without_debt_repayments"]["current"]["minor"], r["expense_without_debt_repayments"]["previous"]["minor"]) == (400_000, 1_000_000)
        assert r["debt_repayments"]["current"]["minor"] == r["debt_repayments"]["previous"]["minor"] == 0
        assert not any("погашен" in w.lower() for w in r["warnings"])  # подтверждённый перевод — не о чём предупреждать

    def test_repayment_does_not_inflate_living_expenses_in_both_periods(self, seeded_client):
        b = Book(seeded_client)
        a = b.account(initial=50_000_000)
        history(b, a)
        b.tx(a, 1_000_000, "2026-09-03T09:00:00Z", "Одежда и обувь")  # покупка по кредитке записана расходом
        self.card_debt(seeded_client, a, 1_000_000, "2026-09-20T09:00:00Z")  # и её погашение — платежом по долгу
        b.tx(a, 400_000, "2026-10-03T09:00:00Z", "Одежда и обувь")
        self.card_debt(seeded_client, a, 400_000, "2026-10-20T09:00:00Z")
        r = rub_of(comparison(seeded_client))
        living = r["expense_without_debt_repayments"]
        assert (living["current"]["minor"], living["previous"]["minor"]) == (400_000, 1_000_000)
        assert (r["debt_repayments"]["current"]["minor"], r["debt_repayments"]["previous"]["minor"]) == (400_000, 1_000_000)
        # погашения не попадают в изменения по категориям и в крупные расходы
        assert {c["label"] for c in r["categories"]} == {"Одежда и обувь"}
        assert "Погашение долга" not in r["summary"]
        assert "Расходы на жизнь снизились на 6 000,00 ₽ (-60,0%)" in r["summary"]
        # неопределённость названа явно, а не «двойного учёта нет»
        assert any("не может проверить" in w for w in r["warnings"])
        assert r["confidence"] != "high"

    def test_repayment_without_recorded_purchase_is_uncertain(self, seeded_client):
        """Покупки по кредитке в приложении нет — погашение единственный след
        трат. Приложение не делает вид, что знает, и говорит, что расходы на
        жизнь могут быть занижены."""
        b = Book(seeded_client)
        a = b.account(initial=50_000_000)
        history(b, a)
        self.card_debt(seeded_client, a, 900_000, "2026-10-20T09:00:00Z")
        r = rub_of(comparison(seeded_client))
        assert r["expense_without_debt_repayments"]["current"]["minor"] == 0
        assert r["expense"]["current"]["minor"] == 900_000  # денежный поток честно включает погашение
        warning = next(w for w in r["warnings"] if "не может проверить" in w)
        assert "занижены" in warning
