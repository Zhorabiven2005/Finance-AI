"""Тесты чистой логики регулярных операций: следующая дата, пропущенные
даты, ограничение end_date, защита от бесконечного цикла."""

from datetime import date

from app.engine.recurring import next_occurrence, pending_occurrences


class TestNextOccurrence:
    def test_daily(self):
        assert next_occurrence(date(2026, 9, 1), "daily") == date(2026, 9, 2)

    def test_weekly(self):
        assert next_occurrence(date(2026, 9, 1), "weekly") == date(2026, 9, 8)

    def test_monthly(self):
        assert next_occurrence(date(2026, 9, 1), "monthly") == date(2026, 10, 1)

    def test_yearly(self):
        assert next_occurrence(date(2026, 9, 1), "yearly") == date(2027, 9, 1)

    def test_monthly_crosses_year_boundary(self):
        assert next_occurrence(date(2026, 12, 15), "monthly") == date(2027, 1, 15)

    def test_monthly_clamps_end_of_month(self):
        # 31 января + 1 месяц: февраля 31-го не существует.
        assert next_occurrence(date(2026, 1, 31), "monthly") == date(2026, 2, 28)

    def test_monthly_clamps_leap_february(self):
        assert next_occurrence(date(2028, 1, 31), "monthly") == date(2028, 2, 29)


class TestPendingOccurrences:
    def test_single_due_date(self):
        occurrences, next_run, active = pending_occurrences(
            date(2026, 9, 1), date(2026, 9, 1), "monthly", None
        )
        assert occurrences == [date(2026, 9, 1)]
        assert next_run == date(2026, 10, 1)
        assert active is True

    def test_not_yet_due_returns_empty(self):
        occurrences, next_run, active = pending_occurrences(
            date(2026, 10, 1), date(2026, 9, 15), "monthly", None
        )
        assert occurrences == []
        assert next_run == date(2026, 10, 1)
        assert active is True

    def test_several_missed_daily_dates(self):
        # next_run_date=01.09, current_date=05.09, daily -> 5 дат.
        occurrences, next_run, active = pending_occurrences(
            date(2026, 9, 1), date(2026, 9, 5), "daily", None
        )
        assert occurrences == [
            date(2026, 9, 1),
            date(2026, 9, 2),
            date(2026, 9, 3),
            date(2026, 9, 4),
            date(2026, 9, 5),
        ]
        assert next_run == date(2026, 9, 6)
        assert active is True

    def test_idempotent_second_call_with_advanced_next_run_date(self):
        """Ключевой сценарий идемпотентности на уровне чистой функции: если
        next_run_date уже продвинут за current_date (как после первого
        успешного запуска), повторный вызов не возвращает те же даты."""
        occurrences, _, _ = pending_occurrences(date(2026, 9, 6), date(2026, 9, 5), "daily", None)
        assert occurrences == []

    def test_weekly_missed_occurrences(self):
        occurrences, next_run, _ = pending_occurrences(
            date(2026, 9, 1), date(2026, 9, 22), "weekly", None
        )
        assert occurrences == [date(2026, 9, 1), date(2026, 9, 8), date(2026, 9, 15), date(2026, 9, 22)]
        assert next_run == date(2026, 9, 29)

    def test_monthly_missed_occurrences(self):
        occurrences, next_run, _ = pending_occurrences(
            date(2026, 7, 1), date(2026, 10, 1), "monthly", None
        )
        assert occurrences == [date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1)]
        assert next_run == date(2026, 11, 1)

    def test_yearly_missed_occurrences(self):
        occurrences, next_run, _ = pending_occurrences(
            date(2024, 1, 1), date(2026, 6, 1), "yearly", None
        )
        assert occurrences == [date(2024, 1, 1), date(2025, 1, 1), date(2026, 1, 1)]
        assert next_run == date(2027, 1, 1)

    def test_end_date_excludes_later_occurrences_and_deactivates(self):
        occurrences, next_run, active = pending_occurrences(
            date(2026, 9, 1), date(2026, 12, 1), "monthly", end_date=date(2026, 10, 15)
        )
        assert occurrences == [date(2026, 9, 1), date(2026, 10, 1)]
        assert next_run == date(2026, 11, 1)
        assert active is False

    def test_end_date_exactly_on_occurrence_still_included(self):
        occurrences, next_run, active = pending_occurrences(
            date(2026, 9, 1), date(2026, 12, 1), "monthly", end_date=date(2026, 10, 1)
        )
        assert occurrences == [date(2026, 9, 1), date(2026, 10, 1)]
        assert active is False

    def test_end_date_not_yet_reached_stays_active(self):
        occurrences, next_run, active = pending_occurrences(
            date(2026, 9, 1), date(2026, 9, 1), "monthly", end_date=date(2026, 12, 31)
        )
        assert occurrences == [date(2026, 9, 1)]
        assert active is True

    def test_max_occurrences_caps_runaway_generation(self):
        # next_run_date на много лет в прошлом при ежедневной частоте —
        # без ограничения это были бы тысячи дат за один вызов.
        occurrences, next_run, active = pending_occurrences(
            date(2000, 1, 1), date(2026, 9, 27), "daily", None, max_occurrences=10
        )
        assert len(occurrences) == 10
        assert occurrences[0] == date(2000, 1, 1)
        assert occurrences[-1] == date(2000, 1, 10)
        assert next_run == date(2000, 1, 11)
        assert active is True

    def test_no_end_date_never_deactivates(self):
        _, _, active = pending_occurrences(date(2026, 1, 1), date(2030, 1, 1), "yearly", None)
        assert active is True
