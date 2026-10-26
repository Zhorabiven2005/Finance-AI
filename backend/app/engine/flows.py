"""Единые правила учёта операций в доходах и расходах (Stage 3F).

Одна функция flow_kind решает, чем операция является для финансовых
показателей. Её используют все экраны и расчёты: аналитика, дашборд,
бюджеты, финансовый контекст, уведомления, инсайты, сравнение периодов и
предупреждения — чтобы одна и та же операция нигде не считалась по-разному.

Виды:
  * "income" — доход;
  * "expense" — расход на жизнь (покупки, услуги, комиссии);
  * "debt_repayment" — погашение долга или кредитки: деньги ушли, но это не
    новая трата. Входит в «все расходы» (денежный поток), но не в расходы
    на жизнь — иначе покупка по кредитке, уже записанная расходом, и её
    погашение учитывались бы дважды;
  * "transfer" — перевод между своими счетами или на свой внешний продукт:
    не доход и не расход вовсе.

Источник вида — только явные данные, без догадок:
  * назначение, которое пользователь выбрал вручную (Transaction.purpose);
  * операция платежа по долгу (debt_payment_id) или категория
    «Погашение долга» — как и раньше (Stage 3D).
Операции без назначения считаются по своему типу, как до Stage 3F.

Баланс счёта от вида не зависит: деньги действительно пришли или ушли.

Модуль без FastAPI и SQLAlchemy: принимает любой объект с полями операции.
"""

from __future__ import annotations

from typing import Literal, Protocol

__all__ = [
    "FlowKind",
    "PURPOSE_OWN_TRANSFER",
    "PURPOSE_EXTERNAL_TRANSFER",
    "PURPOSE_DEBT_REPAYMENT",
    "TRANSFER_PURPOSES",
    "DEBT_REPAYMENT_CATEGORY",
    "flow_kind",
    "is_transfer",
    "debt_repayment_category_ids",
    "allowed_purposes",
]

FlowKind = Literal["income", "expense", "debt_repayment", "transfer"]

PURPOSE_OWN_TRANSFER = "own_transfer"
PURPOSE_EXTERNAL_TRANSFER = "external_transfer"
PURPOSE_DEBT_REPAYMENT = "debt_repayment"
TRANSFER_PURPOSES = frozenset({PURPOSE_OWN_TRANSFER, PURPOSE_EXTERNAL_TRANSFER})

# Категория журнала долгов (api/v1/debts.py): операция в ней — погашение.
DEBT_REPAYMENT_CATEGORY = "Погашение долга"


class _Tx(Protocol):
    type: str
    purpose: str | None
    debt_payment_id: int | None
    category_id: int


def flow_kind(tx: _Tx, debt_category_ids: frozenset[int] | set[int] = frozenset()) -> FlowKind:
    """Вид операции для доходов и расходов. debt_category_ids — id категорий
    расходов «Погашение долга» (см. debt_repayment_category_ids)."""
    purpose = getattr(tx, "purpose", None)
    if purpose in TRANSFER_PURPOSES:
        return "transfer"
    if tx.type == "income":
        return "income"
    if purpose == PURPOSE_DEBT_REPAYMENT or tx.debt_payment_id is not None or tx.category_id in debt_category_ids:
        return "debt_repayment"
    return "expense"


def is_transfer(tx: _Tx) -> bool:
    """Отмечена пользователем как перевод (между своими счетами или на свой
    внешний продукт): не доход и не расход ни в одном показателе."""
    return getattr(tx, "purpose", None) in TRANSFER_PURPOSES


def debt_repayment_category_ids(categories) -> frozenset[int]:
    """id категорий расходов «Погашение долга» из итерируемого набора
    категорий (любых объектов с id, type, name)."""
    return frozenset(c.id for c in categories if c.type == "expense" and c.name == DEBT_REPAYMENT_CATEGORY)


def allowed_purposes(tx_type: str) -> tuple[str, ...]:
    """Какие назначения можно выбрать для операции этого типа. Погашение
    долга — только у расхода; приход от своего счёта или своего внешнего
    продукта — перевод."""
    if tx_type == "expense":
        return (PURPOSE_OWN_TRANSFER, PURPOSE_EXTERNAL_TRANSFER, PURPOSE_DEBT_REPAYMENT)
    return (PURPOSE_OWN_TRANSFER, PURPOSE_EXTERNAL_TRANSFER)
