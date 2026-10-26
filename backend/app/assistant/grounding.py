"""Сверка чисел в ответе модели с данными (Stage 3B).

Модель не считает деньги — она пересказывает значения, уже посчитанные
приложением. После ответа backend находит в тексте все числа и проверяет,
встречаются ли они в том, что модель получила: в сводке данных или в
сообщениях пользователя. Число, которого там нет (например, «сумма» рублей и
долларов или неверно посчитанный срок), помечается как непроверенное — UI
показывает это пользователю.

Сравниваются значения, а не написание: «36 000 рублей», «36 000,00 ₽» и
«36000» — одно и то же число. Знак не учитывается (−10 000 и 10 000 ↔ «итог
−10 000» и «потратили 10 000»). Номера пунктов списка («1.», «2)») в начале
строки не проверяются.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

# Число с группами разрядов (пробел, неразрывный и узкий пробел) и дробной
# частью через запятую или точку; либо простое число.
_NUMBER = re.compile(
    r"(?<![\w.,])(?:\d{1,3}(?:[   ]\d{3})+|\d+)(?:[.,]\d+)?(?![\w])"
)
_LIST_MARKER = re.compile(r"^\s*\d{1,2}[.)]\s", re.MULTILINE)


def _value(token: str) -> Decimal | None:
    cleaned = re.sub(r"[   ]", "", token).replace(",", ".")
    try:
        return Decimal(cleaned).normalize()
    except InvalidOperation:
        return None


def numbers(text: str) -> list[tuple[str, Decimal]]:
    text = _LIST_MARKER.sub(" ", text)
    out = []
    for m in _NUMBER.finditer(text):
        v = _value(m.group(0))
        if v is not None:
            out.append((m.group(0).strip(), v))
    return out


@dataclass(frozen=True)
class Grounding:
    checked: int
    unverified: list[str]


def check_numbers(answer: str, sources: list[str]) -> Grounding:
    allowed = {v for src in sources for _, v in numbers(src)}
    found = numbers(answer)
    unverified: list[str] = []
    for raw, value in found:
        if value not in allowed and raw not in unverified:
            unverified.append(raw)
    return Grounding(checked=len(found), unverified=unverified)
