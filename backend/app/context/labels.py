"""Пользовательские названия в финансовом контексте.

Названия счетов, категорий, долгов и целей — недоверенные данные: будущая
модель должна видеть в них текст, а не инструкции. Здесь они только
приводятся к безопасному виду для ответа (в БД ничего не меняется):
управляющие и невидимые символы форматирования (в том числе переключатели
направления текста) заменяются пробелом, длина ограничивается.
"""

from __future__ import annotations

import unicodedata

MAX_LABEL_LENGTH = 200


def sanitize_label(raw: str | None) -> tuple[str, bool]:
    """Безопасное представление метки и флаг «пришлось изменить»."""
    text = raw or ""
    cleaned = "".join(" " if unicodedata.category(ch) in ("Cc", "Cf") else ch for ch in text)
    if len(cleaned) > MAX_LABEL_LENGTH:
        cleaned = cleaned[: MAX_LABEL_LENGTH - 1] + "…"
    return cleaned, cleaned != text
