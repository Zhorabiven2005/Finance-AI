"""Расчёт баланса счёта.

Баланс никогда не хранится как отдельное персистентное поле, которое нужно
инкрементировать/декрементировать вручную при каждой операции — источник
истины это начальный баланс счёта плюс сумма всех операций по нему. Такой
подход по конструкции исключает рассинхронизацию баланса с историей операций
после редактирования или удаления транзакции: баланс всегда пересчитывается
с нуля.

Модуль не зависит ни от FastAPI, ни от SQLAlchemy — на вход подаются уже
собранные подписанные суммы (Money), а не ORM-объекты.
"""

from __future__ import annotations

from typing import Iterable

from app.engine.money import Currency, Money, money_sum

__all__ = ["account_balance"]


def account_balance(
    initial_balance: Money,
    signed_entries: Iterable[Money],
    currency: Currency | str | None = None,
) -> Money:
    """Баланс = начальный баланс + сумма подписанных операций.

    Подписанные суммы (signed_entries) — это то, что уже учитывает
    направление движения денег: доход и перевод-зачисление положительны,
    расход и перевод-списание отрицательны.
    """
    cur = initial_balance.currency if currency is None else currency
    return money_sum([initial_balance, *signed_entries], cur)
