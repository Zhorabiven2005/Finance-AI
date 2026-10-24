"""Расчёт сводных показателей главного экрана.

Чистый капитал = сумма балансов счетов + то, что должны нам − то, что должны
мы. Модуль принимает уже посчитанные Money, а не запросы к базе.
"""

from __future__ import annotations

from typing import Iterable

from app.engine.money import Currency, Money, money_sum

__all__ = ["net_worth"]


def net_worth(
    account_balances: Iterable[Money],
    owed_to_me: Iterable[Money],
    i_owe: Iterable[Money],
    currency: Currency | str,
) -> Money:
    accounts_total = money_sum(account_balances, currency)
    owed_to_me_total = money_sum(owed_to_me, currency)
    i_owe_total = money_sum(i_owe, currency)
    return accounts_total + owed_to_me_total - i_owe_total
