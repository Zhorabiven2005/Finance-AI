"""Тесты чистой логики бюджетов: остаток, процент, статус, границы месяца."""

from datetime import datetime, timezone
from decimal import Decimal

from app.engine.budgets import (
    BudgetStatus,
    calculate_budget_status,
    calculate_budget_usage,
    calculate_remaining,
    calculate_usage_percent,
    month_bounds,
)
from app.engine.money import Money, get_currency

RUB = get_currency("RUB")


class TestCalculateRemaining:
    def test_spent_less_than_budget(self):
        remaining = calculate_remaining(Money.from_major("30000", RUB), Money.from_major("24000", RUB))
        assert remaining == Money.from_major("6000", RUB)

    def test_spent_equals_budget(self):
        remaining = calculate_remaining(Money.from_major("30000", RUB), Money.from_major("30000", RUB))
        assert remaining.is_zero

    def test_spent_exceeds_budget_is_negative(self):
        remaining = calculate_remaining(Money.from_major("30000", RUB), Money.from_major("34000", RUB))
        assert remaining == Money.from_major("-4000", RUB)

    def test_zero_spent(self):
        remaining = calculate_remaining(Money.from_major("30000", RUB), Money.zero(RUB))
        assert remaining == Money.from_major("30000", RUB)


class TestCalculateUsagePercent:
    def test_zero_spent_is_zero_percent(self):
        assert calculate_usage_percent(Money.zero(RUB), Money.from_major("30000", RUB)) == Decimal(0)

    def test_spent_less_than_budget(self):
        percent = calculate_usage_percent(Money.from_major("24000", RUB), Money.from_major("30000", RUB))
        assert percent == Decimal("80.0")

    def test_spent_equals_budget_is_100(self):
        percent = calculate_usage_percent(Money.from_major("30000", RUB), Money.from_major("30000", RUB))
        assert percent == Decimal("100.0")

    def test_spent_exceeds_budget(self):
        percent = calculate_usage_percent(Money.from_major("34000", RUB), Money.from_major("30000", RUB))
        assert percent == Decimal("113.3")

    def test_budget_zero_does_not_raise(self):
        assert calculate_usage_percent(Money.from_major("100", RUB), Money.zero(RUB)) == Decimal(0)

    def test_budget_zero_and_spent_zero(self):
        assert calculate_usage_percent(Money.zero(RUB), Money.zero(RUB)) == Decimal(0)

    def test_rounding_to_one_decimal(self):
        # 1/3 * 100 = 33.333...% -> округляется до 33.3
        percent = calculate_usage_percent(Money.of(1, RUB), Money.of(3, RUB))
        assert percent == Decimal("33.3")

    def test_large_values(self):
        percent = calculate_usage_percent(
            Money.from_major("999999999", RUB), Money.from_major("1000000000", RUB)
        )
        assert percent == Decimal("100.0")


class TestCalculateBudgetStatus:
    def test_well_under_budget_is_ok(self):
        status = calculate_budget_status(Money.from_major("1000", RUB), Money.from_major("30000", RUB))
        assert status is BudgetStatus.ok

    def test_just_under_80_percent_is_ok(self):
        # 23900 / 30000 = 79.66...% -> округляется до 79.7%, всё ещё "ok".
        status = calculate_budget_status(Money.from_major("23900", RUB), Money.from_major("30000", RUB))
        assert status is BudgetStatus.ok

    def test_exactly_80_percent_is_warning(self):
        status = calculate_budget_status(Money.from_major("24000", RUB), Money.from_major("30000", RUB))
        assert status is BudgetStatus.warning

    def test_between_80_and_100_is_warning(self):
        status = calculate_budget_status(Money.from_major("27000", RUB), Money.from_major("30000", RUB))
        assert status is BudgetStatus.warning

    def test_exactly_100_percent_is_warning_not_exceeded(self):
        status = calculate_budget_status(Money.from_major("30000", RUB), Money.from_major("30000", RUB))
        assert status is BudgetStatus.warning

    def test_over_100_percent_is_exceeded(self):
        status = calculate_budget_status(Money.from_major("34000", RUB), Money.from_major("30000", RUB))
        assert status is BudgetStatus.exceeded

    def test_zero_budget_zero_spent_is_ok(self):
        assert calculate_budget_status(Money.zero(RUB), Money.zero(RUB)) is BudgetStatus.ok

    def test_zero_budget_any_spending_is_exceeded(self):
        # Раз лимит 0, а потратили хоть что-то — это уже превышение, даже
        # если процент формально не вычислим.
        status = calculate_budget_status(Money.of(1, RUB), Money.zero(RUB))
        assert status is BudgetStatus.exceeded


class TestCalculateBudgetUsage:
    def test_combined_result_matches_individual_calculations(self):
        spent = Money.from_major("24000", RUB)
        budget = Money.from_major("30000", RUB)
        remaining, percent, status = calculate_budget_usage(spent, budget)
        assert remaining == calculate_remaining(budget, spent)
        assert percent == calculate_usage_percent(spent, budget)
        assert status == calculate_budget_status(spent, budget)
        assert status is BudgetStatus.warning


class TestMonthBounds:
    def test_regular_month(self):
        start, end = month_bounds(2026, 9)
        assert start == datetime(2026, 9, 1, tzinfo=timezone.utc)
        assert end == datetime(2026, 9, 30, 23, 59, 59, 999999, tzinfo=timezone.utc)

    def test_december_rolls_into_next_year(self):
        start, end = month_bounds(2026, 12)
        assert start == datetime(2026, 12, 1, tzinfo=timezone.utc)
        assert end == datetime(2026, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)

    def test_february_leap_year(self):
        start, end = month_bounds(2028, 2)
        assert end.day == 29

    def test_february_non_leap_year(self):
        start, end = month_bounds(2026, 2)
        assert end.day == 28
