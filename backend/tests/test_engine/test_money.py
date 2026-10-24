"""Тесты денежного типа.

Финансовый движок — самая критичная часть приложения, поэтому Money покрыт
полностью, включая граничные случаи и запрещённые операции.
"""

from decimal import ROUND_DOWN, Decimal

import pytest

from app.engine.money import (
    Currency,
    CurrencyMismatchError,
    Money,
    UnknownCurrencyError,
    get_currency,
    money_sum,
)

RUB = get_currency("RUB")
USD = get_currency("USD")
JPY = get_currency("JPY")


# ----------------------------------------------------------------------
# Реестр валют
# ----------------------------------------------------------------------


class TestCurrency:
    def test_lookup_is_case_insensitive(self):
        assert get_currency("rub") is RUB
        assert get_currency(" RUB ") is RUB

    def test_currency_object_passes_through(self):
        assert get_currency(RUB) is RUB

    def test_unknown_currency_raises(self):
        with pytest.raises(UnknownCurrencyError):
            get_currency("XYZ")

    def test_subunit(self):
        assert RUB.subunit == 100
        assert JPY.subunit == 1

    def test_currency_is_immutable(self):
        with pytest.raises(Exception):
            RUB.code = "USD"  # type: ignore[misc]


# ----------------------------------------------------------------------
# Конструкторы
# ----------------------------------------------------------------------


class TestConstruction:
    def test_of_uses_minor_units(self):
        assert Money.of(1055, "RUB").minor == 1055

    def test_zero(self):
        z = Money.zero("RUB")
        assert z.minor == 0 and z.is_zero

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("10.55", 1055),
            ("10,55", 1055),
            ("0.01", 1),
            ("-10.55", -1055),
            ("1000", 100_000),
            (10, 1000),
            (Decimal("10.55"), 1055),
            (Decimal("0.005"), 1),  # ROUND_HALF_UP
            (Decimal("0.004"), 0),
        ],
    )
    def test_from_major(self, value, expected):
        assert Money.from_major(value, "RUB").minor == expected

    def test_from_major_respects_currency_exponent(self):
        assert Money.from_major("1000", "JPY").minor == 1000

    def test_rounding_policy_is_half_up_not_bankers(self):
        # Банковское округление дало бы 2 копейки, пользователь ожидает 3.
        assert Money.from_major(Decimal("0.025"), "RUB").minor == 3
        assert Money.from_major(Decimal("0.035"), "RUB").minor == 4

    def test_rounding_can_be_overridden(self):
        assert Money.from_major(Decimal("0.999"), "RUB", rounding=ROUND_DOWN).minor == 99

    # --- запрет float -------------------------------------------------

    def test_float_rejected_in_from_major(self):
        with pytest.raises(TypeError, match="float"):
            Money.from_major(10.55, "RUB")

    def test_float_rejected_in_minor(self):
        with pytest.raises(TypeError):
            Money(10.5, RUB)  # type: ignore[arg-type]

    def test_float_rejected_in_multiplication(self):
        with pytest.raises(TypeError, match="float"):
            Money.of(1000, "RUB") * 1.5

    def test_bool_is_not_a_number(self):
        with pytest.raises(TypeError):
            Money(True, RUB)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            Money.from_major(True, "RUB")  # type: ignore[arg-type]

    def test_non_finite_rejected(self):
        with pytest.raises(ValueError):
            Money.from_major(Decimal("NaN"), "RUB")
        with pytest.raises(ValueError):
            Money.from_major(Decimal("Infinity"), "RUB")

    def test_garbage_string_rejected(self):
        with pytest.raises(ValueError):
            Money.from_major("десять рублей", "RUB")


class TestParse:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("1 234,56", 123_456),
            ("1234.56", 123_456),
            ("1\u00a0234,56\u00a0\u20bd", 123_456),
            ("1234,56 RUB", 123_456),
            ("-1 234,56", -123_456),
            ("  42  ", 4200),
        ],
    )
    def test_parse_user_input(self, text, expected):
        assert Money.parse(text, "RUB").minor == expected

    def test_parse_empty_rejected(self):
        with pytest.raises(ValueError):
            Money.parse("   ", "RUB")

    def test_parse_requires_string(self):
        with pytest.raises(TypeError):
            Money.parse(100, "RUB")  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# Представление
# ----------------------------------------------------------------------


class TestRepresentation:
    def test_to_decimal_is_exact(self):
        assert Money.of(1055, "RUB").to_decimal() == Decimal("10.55")
        assert Money.of(-1, "RUB").to_decimal() == Decimal("-0.01")

    def test_to_decimal_keeps_scale(self):
        assert str(Money.of(1000, "RUB").to_decimal()) == "10.00"

    def test_format(self):
        assert Money.of(123_456, "RUB").format() == "1\u00a0234,56\u00a0\u20bd"
        assert Money.of(-50, "RUB").format() == "-0,50\u00a0\u20bd"
        assert Money.of(0, "RUB").format() == "0,00\u00a0\u20bd"

    def test_format_without_symbol(self):
        assert Money.of(123_456, "RUB").format(with_symbol=False) == "1\u00a0234,56"

    def test_format_zero_exponent_currency(self):
        assert Money.of(1500, "JPY").format(with_symbol=False) == "1\u00a0500"

    def test_repr_roundtrip(self):
        assert repr(Money.of(1055, "RUB")) == "Money(1055, 'RUB')"


# ----------------------------------------------------------------------
# Арифметика
# ----------------------------------------------------------------------


class TestArithmetic:
    def test_add_and_sub(self):
        a, b = Money.of(1055, "RUB"), Money.of(45, "RUB")
        assert (a + b).minor == 1100
        assert (a - b).minor == 1010

    def test_neg_and_abs(self):
        assert (-Money.of(1055, "RUB")).minor == -1055
        assert abs(Money.of(-1055, "RUB")).minor == 1055

    def test_multiply_by_int_is_exact(self):
        assert (Money.of(333, "RUB") * 3).minor == 999
        assert (3 * Money.of(333, "RUB")).minor == 999

    def test_multiply_by_decimal_rounds(self):
        assert (Money.of(1000, "RUB") * Decimal("1.5")).minor == 1500
        assert (Money.of(101, "RUB") * Decimal("0.5")).minor == 51  # 50.5 -> 51

    def test_percent(self):
        assert Money.of(10_000, "RUB").percent(15).minor == 1500
        assert Money.of(10_000, "RUB").percent(Decimal("0.5")).minor == 50

    def test_ratio_to(self):
        spent, budget = Money.of(7500, "RUB"), Money.of(10_000, "RUB")
        assert spent.ratio_to(budget) == Decimal("0.75")

    def test_ratio_to_zero_raises(self):
        with pytest.raises(ZeroDivisionError):
            Money.of(100, "RUB").ratio_to(Money.zero("RUB"))

    def test_no_float_accumulation_error(self):
        # Классический случай, на котором ломается float: 0.1 + 0.2 != 0.3
        total = money_sum(
            [Money.from_major("0.1", "RUB"), Money.from_major("0.2", "RUB")], "RUB"
        )
        assert total == Money.from_major("0.3", "RUB")

    def test_thousand_additions_stay_exact(self):
        total = money_sum([Money.of(1, "RUB")] * 1000, "RUB")
        assert total.minor == 1000

    def test_immutability(self):
        m = Money.of(1000, "RUB")
        _ = m + Money.of(500, "RUB")
        assert m.minor == 1000
        with pytest.raises(Exception):
            m.minor = 5  # type: ignore[misc]


class TestCurrencyMismatch:
    @pytest.mark.parametrize(
        "op",
        [
            lambda a, b: a + b,
            lambda a, b: a - b,
            lambda a, b: a < b,
            lambda a, b: a >= b,
            lambda a, b: a.ratio_to(b),
        ],
    )
    def test_mixed_currency_operations_raise(self, op):
        with pytest.raises(CurrencyMismatchError):
            op(Money.of(100, "RUB"), Money.of(100, "USD"))

    def test_equality_across_currencies_is_false_not_error(self):
        # Сравнение на равенство — безопасная операция, ошибку не бросаем.
        assert Money.of(100, "RUB") != Money.of(100, "USD")

    def test_adding_non_money_raises(self):
        with pytest.raises(TypeError):
            Money.of(100, "RUB") + 100  # type: ignore[operator]


class TestComparison:
    def test_ordering(self):
        assert Money.of(100, "RUB") < Money.of(200, "RUB")
        assert Money.of(200, "RUB") > Money.of(100, "RUB")
        assert Money.of(100, "RUB") <= Money.of(100, "RUB")
        assert Money.of(100, "RUB") >= Money.of(100, "RUB")

    def test_equality_and_hash(self):
        assert Money.of(100, "RUB") == Money.of(100, "RUB")
        assert len({Money.of(100, "RUB"), Money.of(100, "RUB")}) == 1

    def test_sorting(self):
        items = [Money.of(300, "RUB"), Money.of(100, "RUB"), Money.of(200, "RUB")]
        assert [m.minor for m in sorted(items)] == [100, 200, 300]

    def test_predicates(self):
        assert Money.of(1, "RUB").is_positive
        assert Money.of(-1, "RUB").is_negative
        assert Money.zero("RUB").is_zero


# ----------------------------------------------------------------------
# Распределение — здесь теряются копейки в наивных реализациях
# ----------------------------------------------------------------------


class TestAllocation:
    def test_split_preserves_total(self):
        parts = Money.of(100, "RUB").split(3)
        assert [p.minor for p in parts] == [34, 33, 33]
        assert money_sum(parts, "RUB").minor == 100

    def test_split_exact_division(self):
        parts = Money.of(900, "RUB").split(3)
        assert [p.minor for p in parts] == [300, 300, 300]

    def test_allocate_by_weights(self):
        parts = Money.of(10_000, "RUB").allocate([70, 20, 10])
        assert [p.minor for p in parts] == [7000, 2000, 1000]

    def test_allocate_distributes_remainder(self):
        parts = Money.of(5, "RUB").allocate([3, 7])
        assert money_sum(parts, "RUB").minor == 5
        assert [p.minor for p in parts] == [2, 3]

    def test_allocate_handles_zero_weight(self):
        parts = Money.of(100, "RUB").allocate([1, 0, 1])
        assert [p.minor for p in parts] == [50, 0, 50]

    def test_allocate_negative_amount(self):
        parts = Money.of(-100, "RUB").split(3)
        assert money_sum(parts, "RUB").minor == -100
        assert [p.minor for p in parts] == [-34, -33, -33]

    @pytest.mark.parametrize("amount", [1, 7, 99, 100, 101, 999, 123_456])
    @pytest.mark.parametrize("parts", [1, 2, 3, 7, 13])
    def test_split_never_loses_money(self, amount, parts):
        result = Money.of(amount, "RUB").split(parts)
        assert len(result) == parts
        assert money_sum(result, "RUB").minor == amount

    def test_split_is_deterministic(self):
        assert Money.of(100, "RUB").split(3) == Money.of(100, "RUB").split(3)

    def test_invalid_allocation_input(self):
        with pytest.raises(ValueError):
            Money.of(100, "RUB").allocate([])
        with pytest.raises(ValueError):
            Money.of(100, "RUB").allocate([0, 0])
        with pytest.raises(ValueError):
            Money.of(100, "RUB").allocate([-1, 2])
        with pytest.raises(ValueError):
            Money.of(100, "RUB").split(0)
        with pytest.raises(TypeError):
            Money.of(100, "RUB").split("3")  # type: ignore[arg-type]


class TestMoneySum:
    def test_empty_sequence_gives_typed_zero(self):
        total = money_sum([], "RUB")
        assert total.is_zero and total.currency is RUB

    def test_sum_of_mixed_currencies_raises(self):
        with pytest.raises(CurrencyMismatchError):
            money_sum([Money.of(1, "RUB"), Money.of(1, "USD")], "RUB")
