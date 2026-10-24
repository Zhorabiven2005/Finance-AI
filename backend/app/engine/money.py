"""Денежный тип приложения.

Единственный допустимый способ представления денег в системе.

Правила, которые здесь закреплены:
  * сумма хранится как целое число минорных единиц (копейки), не как float;
  * float не принимается ни в одном конструкторе и ни в одной операции;
  * операции между разными валютами запрещены;
  * любое деление возвращает точное распределение без потери копеек.

Модуль намеренно не зависит ни от FastAPI, ни от SQLAlchemy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Iterable, Sequence

__all__ = [
    "Currency",
    "Money",
    "money_sum",
    "CurrencyMismatchError",
    "UnknownCurrencyError",
    "MoneyError",
    "get_currency",
    "REGISTERED_CURRENCIES",
    "DEFAULT_ROUNDING",
]

# Политика округления по умолчанию.
# ROUND_HALF_UP, а не банковское ROUND_HALF_EVEN: пользователь финансового
# приложения ожидает, что 2.5 округлится до 3, а не до 2.
DEFAULT_ROUNDING = ROUND_HALF_UP


class MoneyError(Exception):
    """Базовая ошибка денежных операций."""


class CurrencyMismatchError(MoneyError):
    """Попытка выполнить операцию над суммами в разных валютах."""

    def __init__(self, left: "Currency", right: "Currency") -> None:
        super().__init__(
            f"Операция над разными валютами запрещена: {left.code} и {right.code}"
        )
        self.left = left
        self.right = right


class UnknownCurrencyError(MoneyError):
    """Запрошена валюта, отсутствующая в реестре."""

    def __init__(self, code: str) -> None:
        super().__init__(f"Неизвестная валюта: {code!r}")
        self.code = code


@dataclass(frozen=True, slots=True)
class Currency:
    """Описание валюты.

    exponent — количество знаков после запятой (2 для RUB, 0 для JPY).
    """

    code: str
    exponent: int
    symbol: str
    name: str

    @property
    def subunit(self) -> int:
        """Количество минорных единиц в одной мажорной. Для RUB это 100."""
        return 10**self.exponent


# Реестр валют. В MVP пользователь работает только с RUB, но модель данных
# и вся арифметика с самого начала мультивалютные.
REGISTERED_CURRENCIES: dict[str, Currency] = {
    c.code: c
    for c in (
        Currency("RUB", 2, "\u20bd", "Российский рубль"),
        Currency("USD", 2, "$", "Доллар США"),
        Currency("EUR", 2, "\u20ac", "Евро"),
        Currency("KZT", 2, "\u20b8", "Казахстанский тенге"),
        Currency("JPY", 0, "\u00a5", "Японская иена"),
    )
}


def get_currency(currency: "Currency | str") -> Currency:
    """Возвращает Currency по коду или пропускает готовый объект."""
    if isinstance(currency, Currency):
        return currency
    code = str(currency).strip().upper()
    try:
        return REGISTERED_CURRENCIES[code]
    except KeyError:
        raise UnknownCurrencyError(code) from None


# Разрешённые типы для конвертации в Decimal. float отсутствует намеренно.
_ExactNumber = int | str | Decimal

_PARSE_CLEANUP = re.compile(r"[\s\u00a0\u202f_]")


def _to_decimal(value: _ExactNumber, *, what: str) -> Decimal:
    """Переводит значение в Decimal, запрещая float."""
    if isinstance(value, bool):
        raise TypeError(f"{what}: bool не является денежным значением")
    if isinstance(value, float):
        raise TypeError(
            f"{what}: float запрещён из-за потери точности. "
            f"Передайте int, str или Decimal (например, Decimal('10.55'))."
        )
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"{what}: значение должно быть конечным, получено {value}")
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            parsed = Decimal(_PARSE_CLEANUP.sub("", value).replace(",", "."))
        except InvalidOperation:
            raise ValueError(f"{what}: строку {value!r} нельзя разобрать как число") from None
        if not parsed.is_finite():
            raise ValueError(f"{what}: значение должно быть конечным")
        return parsed
    raise TypeError(f"{what}: неподдерживаемый тип {type(value).__name__}")


@dataclass(frozen=True, slots=True, order=False)
class Money:
    """Денежная сумма. Неизменяемая.

    minor — целое число минорных единиц. 10 рублей 55 копеек это Money(1055, RUB).
    """

    minor: int
    currency: Currency

    def __post_init__(self) -> None:
        if isinstance(self.minor, bool) or not isinstance(self.minor, int):
            raise TypeError(
                "Money.minor должен быть int (минорные единицы). "
                "Для дробных значений используйте Money.from_major()."
            )
        if not isinstance(self.currency, Currency):
            raise TypeError("Money.currency должен быть объектом Currency")

    # ------------------------------------------------------------------
    # Конструкторы
    # ------------------------------------------------------------------

    @classmethod
    def of(cls, minor: int, currency: Currency | str) -> "Money":
        """Из минорных единиц: Money.of(1055, 'RUB') == 10.55 RUB."""
        return cls(minor, get_currency(currency))

    @classmethod
    def zero(cls, currency: Currency | str) -> "Money":
        return cls(0, get_currency(currency))

    @classmethod
    def from_major(
        cls,
        amount: _ExactNumber,
        currency: Currency | str,
        *,
        rounding: str = DEFAULT_ROUNDING,
    ) -> "Money":
        """Из мажорных единиц: Money.from_major('10.55', 'RUB').

        float запрещён. Значения точнее валюты округляются по политике rounding.
        """
        cur = get_currency(currency)
        dec = _to_decimal(amount, what="Money.from_major")
        with localcontext() as ctx:
            ctx.prec = 40
            scaled = (dec * cur.subunit).quantize(Decimal(1), rounding=rounding)
        return cls(int(scaled), cur)

    @classmethod
    def parse(
        cls,
        text: str,
        currency: Currency | str,
        *,
        rounding: str = DEFAULT_ROUNDING,
    ) -> "Money":
        """Разбирает пользовательский ввод: '1 234,56', '-1234.56', '1 234,56 ₽'."""
        if not isinstance(text, str):
            raise TypeError("Money.parse принимает только строку")
        cur = get_currency(currency)
        cleaned = text.strip()
        for token in (cur.symbol, cur.code, cur.code.lower()):
            cleaned = cleaned.replace(token, "")
        cleaned = cleaned.strip()
        if not cleaned:
            raise ValueError(f"Money.parse: пустая строка {text!r}")
        return cls.from_major(cleaned, cur, rounding=rounding)

    # ------------------------------------------------------------------
    # Представление
    # ------------------------------------------------------------------

    def to_decimal(self) -> Decimal:
        """Точное значение в мажорных единицах."""
        return (Decimal(self.minor) / self.currency.subunit).quantize(
            Decimal(1).scaleb(-self.currency.exponent)
        )

    def format(self, *, with_symbol: bool = True, grouping: str = "\u00a0") -> str:
        """Формат для отображения: '1 234,56 ₽'.

        Бэкенд обычно отдаёт minor + код валюты, а форматирует фронтенд.
        Метод нужен для логов, экспорта и текстов AI.
        """
        cur = self.currency
        sign = "-" if self.minor < 0 else ""
        units, frac = divmod(abs(self.minor), cur.subunit)
        int_part = f"{units:,}".replace(",", grouping)
        body = int_part if cur.exponent == 0 else f"{int_part},{frac:0{cur.exponent}d}"
        return f"{sign}{body}\u00a0{cur.symbol}" if with_symbol else f"{sign}{body}"

    def __str__(self) -> str:
        return self.format()

    def __repr__(self) -> str:
        return f"Money({self.minor}, '{self.currency.code}')"

    # ------------------------------------------------------------------
    # Предикаты
    # ------------------------------------------------------------------

    @property
    def is_zero(self) -> bool:
        return self.minor == 0

    @property
    def is_positive(self) -> bool:
        return self.minor > 0

    @property
    def is_negative(self) -> bool:
        return self.minor < 0

    # ------------------------------------------------------------------
    # Арифметика
    # ------------------------------------------------------------------

    def _check(self, other: "Money") -> None:
        if not isinstance(other, Money):
            raise TypeError(f"Ожидался Money, получен {type(other).__name__}")
        if other.currency != self.currency:
            raise CurrencyMismatchError(self.currency, other.currency)

    def __add__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.minor + other.minor, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.minor - other.minor, self.currency)

    def __neg__(self) -> "Money":
        return Money(-self.minor, self.currency)

    def __abs__(self) -> "Money":
        return Money(abs(self.minor), self.currency)

    def __mul__(self, factor: _ExactNumber) -> "Money":
        """Умножение на точное число. Результат округляется до минорной единицы."""
        if isinstance(factor, int) and not isinstance(factor, bool):
            return Money(self.minor * factor, self.currency)
        dec = _to_decimal(factor, what="Money.__mul__")
        with localcontext() as ctx:
            ctx.prec = 40
            scaled = (Decimal(self.minor) * dec).quantize(
                Decimal(1), rounding=DEFAULT_ROUNDING
            )
        return Money(int(scaled), self.currency)

    __rmul__ = __mul__

    def percent(self, value: _ExactNumber) -> "Money":
        """Процент от суммы: Money.of(10000,'RUB').percent(15) == 1500."""
        dec = _to_decimal(value, what="Money.percent")
        return self * (dec / Decimal(100))

    def ratio_to(self, other: "Money") -> Decimal:
        """Доля от другой суммы. Нужна для прогресса целей и бюджетов."""
        self._check(other)
        if other.minor == 0:
            raise ZeroDivisionError("Деление на нулевую сумму")
        with localcontext() as ctx:
            ctx.prec = 28
            return Decimal(self.minor) / Decimal(other.minor)

    # ------------------------------------------------------------------
    # Распределение без потери копеек
    # ------------------------------------------------------------------

    def allocate(self, weights: Sequence[int]) -> list["Money"]:
        """Распределяет сумму пропорционально весам без потери копеек.

        Сумма результата всегда точно равна исходной сумме. Остаток от деления
        раздаётся по одной минорной единице методу наибольшего остатка,
        детерминированно — первым в списке.
        """
        if not weights:
            raise ValueError("allocate: список весов пуст")
        if any(not isinstance(w, int) or isinstance(w, bool) for w in weights):
            raise TypeError("allocate: веса должны быть целыми числами")
        if any(w < 0 for w in weights):
            raise ValueError("allocate: веса не могут быть отрицательными")
        total = sum(weights)
        if total == 0:
            raise ValueError("allocate: сумма весов равна нулю")

        sign = -1 if self.minor < 0 else 1
        amount = abs(self.minor)

        shares = [amount * w // total for w in weights]
        remainder = amount - sum(shares)
        # Раздаём остаток тем, у кого дробная часть больше.
        order = sorted(
            range(len(weights)),
            key=lambda i: (-((amount * weights[i]) % total), i),
        )
        for i in order[:remainder]:
            shares[i] += 1
        return [Money(sign * s, self.currency) for s in shares]

    def split(self, parts: int) -> list["Money"]:
        """Делит сумму на равные части без потери копеек."""
        if not isinstance(parts, int) or isinstance(parts, bool):
            raise TypeError("split: количество частей должно быть int")
        if parts <= 0:
            raise ValueError("split: количество частей должно быть больше нуля")
        return self.allocate([1] * parts)

    # ------------------------------------------------------------------
    # Сравнение
    # ------------------------------------------------------------------

    def __lt__(self, other: "Money") -> bool:
        self._check(other)
        return self.minor < other.minor

    def __le__(self, other: "Money") -> bool:
        self._check(other)
        return self.minor <= other.minor

    def __gt__(self, other: "Money") -> bool:
        self._check(other)
        return self.minor > other.minor

    def __ge__(self, other: "Money") -> bool:
        self._check(other)
        return self.minor >= other.minor


def money_sum(items: Iterable[Money], currency: Currency | str) -> Money:
    """Сумма произвольной последовательности.

    Валюта передаётся явно, чтобы пустая последовательность давала корректный
    ноль, а не падала.
    """
    cur = get_currency(currency)
    total = Money.zero(cur)
    for item in items:
        total = total + item
    return total
