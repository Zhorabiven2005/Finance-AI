"""Чистые правила инсайтов (app/engine/insights.py): без БД и модели."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.engine import insights as rules


class TestNearestRank:
    def test_values_come_from_data(self):
        values = [100, 200, 300, 400]
        assert rules.nearest_rank(values, 50) == 200
        assert rules.nearest_rank(values, 75) == 300
        assert rules.nearest_rank(values, 100) == 400
        assert rules.nearest_rank([7], 25) == 7

    @pytest.mark.parametrize("bad", [0, 101, -5])
    def test_bad_percent(self, bad):
        with pytest.raises(ValueError):
            rules.nearest_rank([1, 2], bad)

    def test_empty(self):
        with pytest.raises(ValueError):
            rules.nearest_rank([], 50)


class TestLargeExpenseThreshold:
    def test_needs_baseline(self):
        assert rules.large_expense_threshold([50_000] * (rules.LARGE_EXPENSE_MIN_BASELINE - 1)) is None

    def test_uniform_spending_uses_median_factor(self):
        t = rules.large_expense_threshold([50_000] * 20)
        assert t is not None and t.median_minor == 50_000 and t.q1_minor == t.q3_minor == 50_000
        assert t.threshold_minor == 250_000  # 5 медиан: обычная покупка подороже — не «крупная»

    def test_spread_spending_uses_iqr(self):
        amounts = [10_000] * 5 + [20_000] * 5 + [30_000] * 5 + [100_000] * 5
        t = rules.large_expense_threshold(amounts)
        # Q1=10 000, медиана=20 000, Q3=30 000 → Q3 + 3·IQR = 90 000 < 5 медиан = 100 000
        assert (t.q1_minor, t.median_minor, t.q3_minor, t.threshold_minor) == (10_000, 20_000, 30_000, 100_000)

    def test_big_amount_alone_is_not_large(self):
        # Все траты по 20 000 ₽: такая сумма для пользователя обычна.
        t = rules.large_expense_threshold([2_000_000] * 30)
        assert 2_000_000 < t.threshold_minor

    def test_times_median_rounding(self):
        assert rules.times_median(1_000_000, 30_000) == Decimal("33.3")
        assert rules.times_median(45_000, 30_000) == Decimal("1.5")
        assert rules.times_median(1_000, 3_000) == Decimal("0.3")
        with pytest.raises(ValueError):
            rules.times_median(100, 0)


class TestCadence:
    D = date(2026, 7, 25)

    def days(self, *offsets):
        return [self.D + timedelta(days=o) for o in offsets]

    def test_monthly(self):
        assert rules.detect_cadence([date(2026, 7, 25), date(2026, 8, 25), date(2026, 9, 25), date(2026, 10, 25)]) == "monthly"

    def test_monthly_with_weekend_shift(self):
        assert rules.detect_cadence(self.days(0, 33, 61)) == "monthly"

    def test_weekly(self):
        assert rules.detect_cadence(self.days(0, 7, 14, 22)) == "weekly"

    def test_two_occurrences_are_not_enough(self):
        assert rules.detect_cadence(self.days(0, 30)) is None

    def test_irregular(self):
        assert rules.detect_cadence(self.days(0, 10, 60)) is None
        assert rules.detect_cadence(self.days(0, 30, 45)) is None

    def test_same_day_is_not_regular(self):
        assert rules.detect_cadence(self.days(0, 0, 30)) is None

    def test_order_does_not_matter(self):
        assert rules.detect_cadence(self.days(60, 0, 30)) == "monthly"


class TestBudgetPace:
    def test_not_estimated_in_first_week(self):
        assert rules.projected_month_spend(500_000, 6, 31) is None

    def test_linear_pace_rounded_up(self):
        # 9 000 ₽ за 25 дней → 9 000 × 31 / 25 = 11 160 ₽
        assert rules.projected_month_spend(900_000, 25, 31) == 1_116_000
        assert rules.projected_month_spend(100, 7, 30) == 429  # 428,57… → вверх

    def test_month_end(self):
        assert rules.projected_month_spend(123, 31, 31) == 123

    def test_zero_spent(self):
        assert rules.projected_month_spend(0, 15, 30) == 0
