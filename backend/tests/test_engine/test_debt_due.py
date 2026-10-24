"""Срок погашения и прогресс долга — чистые функции."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.engine.debts import DEBT_DUE_SOON_DAYS, DebtDueState, debt_due_state, debt_paid_percent
from app.engine.money import Money

TODAY = date(2026, 10, 15)


@pytest.mark.parametrize(
    "due, expected",
    [
        (None, DebtDueState.none),
        (TODAY - timedelta(days=1), DebtDueState.overdue),
        (TODAY - timedelta(days=400), DebtDueState.overdue),
        (TODAY, DebtDueState.today),
        (TODAY + timedelta(days=1), DebtDueState.soon),
        (TODAY + timedelta(days=DEBT_DUE_SOON_DAYS), DebtDueState.soon),
        (TODAY + timedelta(days=DEBT_DUE_SOON_DAYS + 1), DebtDueState.upcoming),
    ],
)
def test_due_states(due, expected):
    assert debt_due_state(due, 100, TODAY) is expected


@pytest.mark.parametrize("due", [None, TODAY - timedelta(days=30), TODAY, TODAY + timedelta(days=3)])
def test_paid_debt_is_paid_regardless_of_due(due):
    assert debt_due_state(due, 0, TODAY) is DebtDueState.paid


def test_soon_threshold_is_seven_days():
    assert DEBT_DUE_SOON_DAYS == 7


@pytest.mark.parametrize(
    "principal, remaining, expected",
    [(100_000, 100_000, "0.0"), (100_000, 60_000, "40.0"), (100_000, 0, "100.0"), (3, 2, "33.3"), (100, -50, "100.0"), (100, 150, "0.0")],
)
def test_paid_percent_is_clamped(principal, remaining, expected):
    assert debt_paid_percent(Money.of(principal, "RUB"), Money.of(remaining, "RUB")) == Decimal(expected)


def test_paid_percent_independent_per_currency():
    assert debt_paid_percent(Money.of(1000, "USD"), Money.of(250, "USD")) == Decimal("75.0")
    assert debt_paid_percent(Money.of(1000, "JPY"), Money.of(1000, "JPY")) == Decimal("0.0")
