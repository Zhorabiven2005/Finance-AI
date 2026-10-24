"""Тесты чистых функций расчёта остатка и статуса долга."""

import pytest

from app.engine.debts import DebtStatus, debt_remaining, debt_status
from app.engine.money import Money, get_currency

RUB = get_currency("RUB")


class TestDebtRemaining:
    def test_no_payments_remaining_equals_principal(self):
        principal = Money.from_major("10000", RUB)
        assert debt_remaining(principal, []) == principal

    def test_partial_payment_reduces_remaining(self):
        principal = Money.from_major("10000", RUB)
        remaining = debt_remaining(principal, [Money.from_major("3000", RUB)])
        assert remaining == Money.from_major("7000", RUB)

    def test_multiple_payments_sum_exactly(self):
        principal = Money.from_major("100", RUB)
        payments = [Money.from_major("33.33", RUB)] * 3
        remaining = debt_remaining(principal, payments)
        # 33.33 * 3 = 99.99, остаток 0.01 — копейка не теряется.
        assert remaining == Money.from_major("0.01", RUB)

    def test_full_payment_gives_zero_remaining(self):
        principal = Money.from_major("5000", RUB)
        remaining = debt_remaining(principal, [Money.from_major("5000", RUB)])
        assert remaining.is_zero


class TestDebtStatus:
    def test_no_payments_is_active(self):
        principal = Money.from_major("1000", RUB)
        assert debt_status(principal, principal) is DebtStatus.active

    def test_partial_payment_is_partially_paid(self):
        principal = Money.from_major("1000", RUB)
        remaining = Money.from_major("400", RUB)
        assert debt_status(principal, remaining) is DebtStatus.partially_paid

    def test_zero_remaining_is_paid(self):
        principal = Money.from_major("1000", RUB)
        assert debt_status(principal, Money.zero(RUB)) is DebtStatus.paid

    def test_negative_remaining_is_still_paid(self):
        # Переплата логически не должна случаться (это проверяется на уровне
        # API), но функция статуса всё равно должна вести себя предсказуемо.
        principal = Money.from_major("1000", RUB)
        overpaid = Money.from_major("-50", RUB)
        assert debt_status(principal, overpaid) is DebtStatus.paid
