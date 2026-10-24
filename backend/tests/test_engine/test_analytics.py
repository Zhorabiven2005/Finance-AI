"""Тесты чистой логики аналитики: гранулярность, бакеты, предыдущий период,
проценты."""

from datetime import date, datetime, timezone
from decimal import Decimal

from app.engine.analytics import (
    bucket_key,
    choose_granularity,
    generate_buckets,
    percent_change,
    previous_period,
    share_percent,
)
from app.engine.money import Money, get_currency

RUB = get_currency("RUB")


def dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


class TestChooseGranularity:
    def test_single_day_is_day(self):
        assert choose_granularity(dt("2026-08-01"), dt("2026-08-01")) == "day"

    def test_one_month_is_day(self):
        assert choose_granularity(dt("2026-08-01"), dt("2026-08-31")) == "day"

    def test_three_months_is_week(self):
        assert choose_granularity(dt("2026-06-01"), dt("2026-08-31")) == "week"

    def test_full_year_is_month(self):
        assert choose_granularity(dt("2026-01-01"), dt("2026-12-31")) == "month"

    def test_boundary_31_days_is_day(self):
        assert choose_granularity(dt("2026-08-01"), dt("2026-08-31")) == "day"

    def test_boundary_32_days_is_day(self):
        # Порог намеренно шире календарного месяца — см. комментарий у
        # _DAY_GRANULARITY_MAX_SPAN про сдвиг локальной полуночи в UTC.
        assert choose_granularity(dt("2026-08-01"), dt("2026-09-01")) == "day"

    def test_boundary_33_days_is_week(self):
        assert choose_granularity(dt("2026-08-01"), dt("2026-09-02")) == "week"


class TestBucketKey:
    def test_day_bucket_is_the_date_itself(self):
        assert bucket_key(dt("2026-08-15T13:45:00"), "day") == date(2026, 8, 15)

    def test_week_bucket_is_monday(self):
        # 2026-08-15 — суббота; неделя должна начаться с понедельника 10-го.
        assert bucket_key(dt("2026-08-15"), "week") == date(2026, 8, 10)

    def test_week_bucket_on_monday_is_itself(self):
        assert bucket_key(dt("2026-08-10"), "week") == date(2026, 8, 10)

    def test_month_bucket_is_first_of_month(self):
        assert bucket_key(dt("2026-08-27"), "month") == date(2026, 8, 1)


class TestGenerateBuckets:
    def test_day_buckets_cover_whole_range_inclusive(self):
        buckets = generate_buckets(dt("2026-08-01"), dt("2026-08-05"), "day")
        assert buckets == [date(2026, 8, d) for d in range(1, 6)]

    def test_single_day_range_gives_one_bucket(self):
        assert generate_buckets(dt("2026-08-01"), dt("2026-08-01"), "day") == [date(2026, 8, 1)]

    def test_month_buckets_cross_year_boundary(self):
        buckets = generate_buckets(dt("2026-11-15"), dt("2027-02-10"), "month")
        assert buckets == [date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1), date(2027, 2, 1)]

    def test_week_buckets_are_seven_days_apart(self):
        buckets = generate_buckets(dt("2026-08-01"), dt("2026-08-31"), "week")
        for a, b in zip(buckets, buckets[1:]):
            assert (b - a).days == 7


class TestPreviousPeriod:
    def test_previous_period_same_length_no_overlap(self):
        date_from, date_to = dt("2026-08-01"), dt("2026-08-31T23:59:59.999999")
        prev_from, prev_to = previous_period(date_from, date_to)
        assert prev_to < date_from
        assert (date_to - date_from) == (prev_to - prev_from)

    def test_previous_period_for_single_day(self):
        date_from = date_to = dt("2026-08-15")
        prev_from, prev_to = previous_period(date_from, date_to)
        assert prev_from == prev_to
        assert prev_to < date_from


class TestPercentChange:
    def test_increase(self):
        result = percent_change(Money.from_major("120", RUB), Money.from_major("100", RUB))
        assert result == Decimal("20")

    def test_decrease(self):
        result = percent_change(Money.from_major("80", RUB), Money.from_major("100", RUB))
        assert result == Decimal("-20")

    def test_no_change(self):
        result = percent_change(Money.from_major("100", RUB), Money.from_major("100", RUB))
        assert result == Decimal("0")

    def test_previous_zero_returns_none(self):
        assert percent_change(Money.from_major("100", RUB), Money.zero(RUB)) is None

    def test_both_zero_returns_none(self):
        assert percent_change(Money.zero(RUB), Money.zero(RUB)) is None


class TestSharePercent:
    def test_half_share(self):
        assert share_percent(Money.from_major("50", RUB), Money.from_major("100", RUB)) == Decimal(50)

    def test_full_share(self):
        assert share_percent(Money.from_major("100", RUB), Money.from_major("100", RUB)) == Decimal(100)

    def test_zero_total_returns_zero_not_error(self):
        assert share_percent(Money.from_major("0", RUB), Money.zero(RUB)) == Decimal(0)
