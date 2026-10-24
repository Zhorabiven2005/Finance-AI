"""Тесты чистой логики финансовых целей: остаток, процент, статус."""

from decimal import Decimal

import pytest

from app.engine.goals import GoalStatus, calculate_goal_progress, calculate_goal_remaining, calculate_goal_status
from app.engine.money import CurrencyMismatchError, Money, get_currency

RUB = get_currency("RUB")
USD = get_currency("USD")


class TestCalculateGoalRemaining:
    def test_saved_less_than_target(self):
        remaining = calculate_goal_remaining(Money.from_major("180000", RUB), Money.from_major("72000", RUB))
        assert remaining == Money.from_major("108000", RUB)

    def test_saved_equals_target(self):
        remaining = calculate_goal_remaining(Money.from_major("180000", RUB), Money.from_major("180000", RUB))
        assert remaining.is_zero

    def test_saved_exceeds_target_remaining_is_zero_not_negative(self):
        remaining = calculate_goal_remaining(Money.from_major("180000", RUB), Money.from_major("200000", RUB))
        assert remaining.is_zero

    def test_zero_saved(self):
        remaining = calculate_goal_remaining(Money.from_major("180000", RUB), Money.zero(RUB))
        assert remaining == Money.from_major("180000", RUB)

    def test_mismatched_currency_raises(self):
        # Money сам запрещает вычитание разных валют — это и есть защита от
        # "RUB-цель + USD-взнос", а не отдельная проверка.
        with pytest.raises(CurrencyMismatchError):
            calculate_goal_remaining(Money.from_major("1000", RUB), Money.from_major("1000", USD))


class TestCalculateGoalProgress:
    def test_forty_percent(self):
        percent = calculate_goal_progress(Money.from_major("72000", RUB), Money.from_major("180000", RUB))
        assert percent == Decimal("40.0")

    def test_zero_saved_is_zero_percent(self):
        assert calculate_goal_progress(Money.zero(RUB), Money.from_major("180000", RUB)) == Decimal(0)

    def test_saved_equals_target_is_100(self):
        percent = calculate_goal_progress(Money.from_major("180000", RUB), Money.from_major("180000", RUB))
        assert percent == Decimal("100.0")

    def test_saved_exceeds_target_capped_at_100(self):
        percent = calculate_goal_progress(Money.from_major("250000", RUB), Money.from_major("180000", RUB))
        assert percent == Decimal("100.0")

    def test_rounding_to_one_decimal(self):
        percent = calculate_goal_progress(Money.of(1, RUB), Money.of(3, RUB))
        assert percent == Decimal("33.3")

    def test_large_values(self):
        percent = calculate_goal_progress(
            Money.from_major("999999999", RUB), Money.from_major("1000000000", RUB)
        )
        assert percent == Decimal("100.0")

    def test_target_zero_does_not_raise(self):
        assert calculate_goal_progress(Money.from_major("100", RUB), Money.zero(RUB)) == Decimal(100)
        assert calculate_goal_progress(Money.zero(RUB), Money.zero(RUB)) == Decimal(0)


class TestCalculateGoalStatus:
    def test_below_target_is_active(self):
        status = calculate_goal_status(
            Money.from_major("72000", RUB), Money.from_major("180000", RUB), is_archived=False
        )
        assert status is GoalStatus.active

    def test_at_target_is_completed(self):
        status = calculate_goal_status(
            Money.from_major("180000", RUB), Money.from_major("180000", RUB), is_archived=False
        )
        assert status is GoalStatus.completed

    def test_above_target_is_completed(self):
        status = calculate_goal_status(
            Money.from_major("200000", RUB), Money.from_major("180000", RUB), is_archived=False
        )
        assert status is GoalStatus.completed

    def test_archived_overrides_completed(self):
        status = calculate_goal_status(
            Money.from_major("200000", RUB), Money.from_major("180000", RUB), is_archived=True
        )
        assert status is GoalStatus.archived

    def test_archived_overrides_active(self):
        status = calculate_goal_status(
            Money.from_major("100", RUB), Money.from_major("180000", RUB), is_archived=True
        )
        assert status is GoalStatus.archived
