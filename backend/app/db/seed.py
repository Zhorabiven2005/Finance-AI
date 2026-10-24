"""Базовый набор категорий доходов и расходов.

Заполняется один раз при первом запуске (см. ensure_default_categories(),
вызывается из app/main.py — тот же приём, что и ensure_app_settings() для
единственной строки настроек). Идемпотентно: повторный вызов ничего не
дублирует, потому что проверяет наличие хотя бы одной default-категории.

Список сознательно шире "5-6 категорий" — это рабочий набор для реального
личного бюджета, а не демонстрационная заглушка.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.category import Category

DEFAULT_INCOME_CATEGORIES: list[tuple[str, str]] = [
    ("Зарплата", "💼"),
    ("Премия", "🎯"),
    ("Подработка / фриланс", "🧰"),
    ("Инвестиции", "📈"),
    ("Дивиденды", "💹"),
    ("Проценты по вкладам", "🏦"),
    ("Подарки", "🎁"),
    ("Возврат долга", "↩️"),
    ("Продажа имущества", "🏷️"),
    ("Прочие доходы", "➕"),
]

DEFAULT_EXPENSE_CATEGORIES: list[tuple[str, str]] = [
    ("Продукты", "🛒"),
    ("Кафе и рестораны", "🍽️"),
    ("Транспорт", "🚌"),
    ("Автомобиль", "🚗"),
    ("Жильё", "🏠"),
    ("Коммунальные услуги", "💡"),
    ("Связь и интернет", "📶"),
    ("Здоровье и аптека", "💊"),
    ("Одежда и обувь", "👕"),
    ("Развлечения", "🎬"),
    ("Спорт и фитнес", "🏋️"),
    ("Образование", "📚"),
    ("Подписки и сервисы", "🔁"),
    ("Путешествия", "✈️"),
    ("Дом и быт", "🛋️"),
    ("Красота и уход", "💅"),
    ("Подарки и праздники", "🎉"),
    ("Питомцы", "🐾"),
    ("Дети", "🧸"),
    ("Страхование", "🛡️"),
    ("Налоги и взносы", "🧾"),
    ("Погашение долга", "💳"),
    ("Прочие расходы", "➖"),
]


def ensure_default_categories(db: Session) -> None:
    already_seeded = (
        db.query(Category.id).filter(Category.is_default.is_(True)).first()
        is not None
    )
    if already_seeded:
        return

    for name, icon in DEFAULT_INCOME_CATEGORIES:
        db.add(Category(name=name, type="income", icon=icon, is_default=True))
    for name, icon in DEFAULT_EXPENSE_CATEGORIES:
        db.add(Category(name=name, type="expense", icon=icon, is_default=True))
    db.commit()
