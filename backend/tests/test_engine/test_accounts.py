"""Тесты чистой функции расчёта баланса счёта."""

from app.engine.accounts import account_balance
from app.engine.money import Money, get_currency, money_sum

RUB = get_currency("RUB")


class TestAccountBalance:
    def test_no_entries_returns_initial(self):
        initial = Money.from_major("1000", RUB)
        assert account_balance(initial, []) == initial

    def test_income_increases_balance(self):
        initial = Money.from_major("1000", RUB)
        result = account_balance(initial, [Money.from_major("250.50", RUB)])
        assert result == Money.from_major("1250.50", RUB)

    def test_expense_decreases_balance(self):
        initial = Money.from_major("1000", RUB)
        result = account_balance(initial, [-Money.from_major("300", RUB)])
        assert result == Money.from_major("700", RUB)

    def test_mixed_income_expense_transfers(self):
        initial = Money.from_major("1000", RUB)
        entries = [
            Money.from_major("500", RUB),  # доход
            -Money.from_major("120.30", RUB),  # расход
            -Money.from_major("200", RUB),  # перевод исходящий
            Money.from_major("50", RUB),  # перевод входящий
        ]
        result = account_balance(initial, entries)
        assert result == Money.from_major("1229.70", RUB)

    def test_balance_can_go_negative(self):
        initial = Money.zero(RUB)
        result = account_balance(initial, [-Money.from_major("100", RUB)])
        assert result.minor == -10_000

    def test_no_float_drift_over_many_small_entries(self):
        # Классический случай накопления ошибки float: здесь его быть не может.
        initial = Money.zero(RUB)
        entries = [Money.from_major("0.1", RUB)] * 3
        result = account_balance(initial, entries)
        assert result == Money.from_major("0.3", RUB)

    def test_currency_mismatch_raises(self):
        from app.engine.money import CurrencyMismatchError

        initial = Money.zero(RUB)
        usd_entry = Money.from_major("10", get_currency("USD"))
        try:
            account_balance(initial, [usd_entry])
        except CurrencyMismatchError:
            pass
        else:
            raise AssertionError("ожидалась CurrencyMismatchError")

    def test_recomputation_after_removing_entry_is_correct(self):
        """Имитирует удаление операции: баланс просто пересчитывается заново
        из оставшегося набора, без явного 'отката' предыдущего значения."""
        initial = Money.from_major("1000", RUB)
        entries = [Money.from_major("300", RUB), -Money.from_major("100", RUB)]
        before_delete = account_balance(initial, entries)
        assert before_delete == Money.from_major("1200", RUB)

        entries.pop()  # удалили расход 100
        after_delete = account_balance(initial, entries)
        assert after_delete == Money.from_major("1300", RUB)
