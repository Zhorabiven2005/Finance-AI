"""Правила уведомлений — чистые функции, граничные даты и пороги."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.engine.money import Money
from app.notifications import rules
from app.notifications.rules import BudgetFact, DebtFact, RecurringFact

TODAY = date(2026, 10, 15)
RUB = lambda m: Money.of(m, "RUB")  # noqa: E731


def debt(due, remaining=100_000, direction="i_owe", id_=1):
    return DebtFact(id_, "Банк", direction, RUB(remaining), due)


class TestDebtRules:
    def test_no_due_date_no_notification(self):
        assert rules.debt_candidates([debt(None)], TODAY) == []

    def test_far_due_date_no_notification(self):
        assert rules.debt_candidates([debt(TODAY + timedelta(days=8))], TODAY) == []

    @pytest.mark.parametrize("days", [1, 7])
    def test_soon(self, days):
        [c] = rules.debt_candidates([debt(TODAY + timedelta(days=days))], TODAY)
        assert (c.type, c.severity) == ("debt_due", "info")
        assert c.dedup_key == f"debt_due:1:{(TODAY + timedelta(days=days)).isoformat()}:soon"
        assert (c.entity_type, c.entity_id) == ("debt", 1)

    def test_today(self):
        [c] = rules.debt_candidates([debt(TODAY)], TODAY)
        assert (c.type, c.severity, c.dedup_key) == ("debt_due", "warning", "debt_due:1:2026-10-15:today")

    def test_overdue_from_yesterday(self):
        [c] = rules.debt_candidates([debt(TODAY - timedelta(days=1))], TODAY)
        assert (c.type, c.severity, c.dedup_key) == ("debt_overdue", "danger", "debt_overdue:1:2026-10-14")
        assert "1 день назад" in c.message

    def test_long_overdue_is_one_notification_not_one_per_day(self):
        cs = rules.debt_candidates([debt(TODAY - timedelta(days=400))], TODAY)
        assert len(cs) == 1 and cs[0].type == "debt_overdue"

    def test_paid_debt_never_notifies(self):
        assert rules.debt_candidates([debt(TODAY - timedelta(days=3), remaining=0)], TODAY) == []

    def test_owed_to_me_wording_and_amount(self):
        [c] = rules.debt_candidates([debt(TODAY, direction="owed_to_me", remaining=123_456)], TODAY)
        assert "Долг вам" in c.message and "1 234,56" in c.message
        assert c.data["remaining"] == {"minor": 123_456, "currency": "RUB"}


def budget(spent, amount=100_000, year=2026, month=10, id_=5):
    return BudgetFact(id_, "Продукты", year, month, RUB(amount), RUB(spent))


class TestBudgetRules:
    @pytest.mark.parametrize("spent", [0, 79_900])
    def test_under_warning(self, spent):
        assert rules.budget_candidates([budget(spent)], TODAY) == []

    @pytest.mark.parametrize("spent", [80_000, 100_000])
    def test_warning_from_80_to_100_inclusive(self, spent):
        [c] = rules.budget_candidates([budget(spent)], TODAY)
        assert (c.type, c.dedup_key) == ("budget_warning", "budget_warning:5:2026-10")

    def test_exceeded_replaces_warning(self):
        cs = rules.budget_candidates([budget(100_100)], TODAY)
        assert [c.type for c in cs] == ["budget_exceeded"]
        assert cs[0].dedup_key == "budget_exceeded:5:2026-10"

    def test_status_matches_budgets_page_rounding(self):
        # Статус бюджета считается по проценту, округлённому до 0,1 (см.
        # app/engine/budgets.py) — уведомление обязано совпадать со страницей.
        assert [c.type for c in rules.budget_candidates([budget(79_999)], TODAY)] == ["budget_warning"]
        assert [c.type for c in rules.budget_candidates([budget(100_001)], TODAY)] == ["budget_warning"]

    def test_only_current_month(self):
        old = [budget(500_000, year=2026, month=m, id_=m) for m in range(1, 10)]
        assert rules.budget_candidates(old, TODAY) == []

    def test_threshold_constant(self):
        assert rules.BUDGET_WARNING_PERCENT == 80


class TestSpendingRules:
    def test_no_previous_period(self):
        assert rules.spending_candidates({("RUB", 2026, 9): RUB(1_000_000)}, TODAY) == []

    def test_previous_zero_is_not_compared(self):
        assert rules.spending_candidates({("RUB", 2026, 9): RUB(100), ("RUB", 2026, 8): RUB(0)}, TODAY) == []

    def test_below_threshold(self):
        assert rules.spending_candidates({("RUB", 2026, 9): RUB(129_999), ("RUB", 2026, 8): RUB(100_000)}, TODAY) == []

    def test_at_threshold(self):
        [c] = rules.spending_candidates({("RUB", 2026, 9): RUB(130_000), ("RUB", 2026, 8): RUB(100_000)}, TODAY)
        assert (c.type, c.dedup_key, c.data["growth_percent"]) == ("spending_increased", "spending_increased:RUB:2026-09", 30)

    def test_currencies_are_independent(self):
        expenses = {
            ("RUB", 2026, 9): RUB(100_000),
            ("RUB", 2026, 8): RUB(100_000),
            ("USD", 2026, 9): Money.of(5_000, "USD"),
            ("USD", 2026, 8): Money.of(1_000, "USD"),
        }
        [c] = rules.spending_candidates(expenses, TODAY)
        assert c.dedup_key == "spending_increased:USD:2026-09"
        assert c.data["current"] == {"minor": 5_000, "currency": "USD"}

    def test_current_month_ignored_and_january_rollover(self):
        expenses = {("RUB", 2025, 12): RUB(200_000), ("RUB", 2025, 11): RUB(100_000), ("RUB", 2026, 1): RUB(10**9)}
        [c] = rules.spending_candidates(expenses, date(2026, 1, 5))
        assert c.dedup_key == "spending_increased:RUB:2025-12"

    def test_threshold_constant(self):
        assert rules.SPENDING_INCREASE_THRESHOLD_PERCENT == 30


def rule(next_run, active=True, end=None, id_=9):
    return RecurringFact(id_, "Аренда", "expense", RUB(3_500_000), next_run, end, active)


class TestRecurringRules:
    @pytest.mark.parametrize("days", [0, 1, 2])
    def test_due_soon(self, days):
        nxt = TODAY + timedelta(days=days)
        [c] = rules.recurring_candidates([rule(nxt)], TODAY)
        assert (c.type, c.dedup_key) == ("recurring_transaction_due", f"recurring_transaction_due:9:{nxt.isoformat()}")

    def test_not_yet(self):
        assert rules.recurring_candidates([rule(TODAY + timedelta(days=3))], TODAY) == []

    def test_missed(self):
        [c] = rules.recurring_candidates([rule(TODAY - timedelta(days=1))], TODAY)
        assert (c.type, c.severity, c.dedup_key) == ("recurring_transaction_missed", "warning", "recurring_transaction_missed:9:2026-10-14")

    def test_inactive_or_ended_rules_ignored(self):
        assert rules.recurring_candidates([rule(TODAY, active=False)], TODAY) == []
        assert rules.recurring_candidates([rule(TODAY, end=TODAY - timedelta(days=1))], TODAY) == []

    def test_long_missed_rule_is_one_notification(self):
        assert len(rules.recurring_candidates([rule(TODAY - timedelta(days=200))], TODAY)) == 1


def test_all_types_are_consistent_with_model():
    from app.db.models.notification import NOTIFICATION_TYPES

    assert set(rules.ENGINE_TYPES) | {rules.T_SYSTEM} == set(NOTIFICATION_TYPES)
