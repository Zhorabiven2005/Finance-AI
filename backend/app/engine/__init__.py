"""Financial Engine — все финансовые расчёты.

Модули этого пакета не зависят от FastAPI и SQLAlchemy: они принимают
простые структуры данных и возвращают результаты. Это делает расчёты
тестируемыми без базы и веб-слоя.
"""

from app.engine.money import Currency, Money, get_currency, money_sum

__all__ = ["Money", "Currency", "get_currency", "money_sum"]
