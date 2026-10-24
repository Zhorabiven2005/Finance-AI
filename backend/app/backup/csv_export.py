"""Табличный экспорт в CSV. Не заменяет JSON-backup: это удобный просмотр в
Excel, а не формат полного восстановления.

Формат: UTF-8 с BOM (иначе Excel откроет кириллицу как кракозябры),
разделитель «;» (русский Excel ждёт именно его, «,» там — десятичный
разделитель), перевод строки CRLF. Деньги — целые минорные единицы
(amount_minor) плюс точная десятичная запись (amount) без float.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backup.exporter import iso_utc
from app.db.models import Account, Debt, Goal, Transaction, Transfer
from app import clock
from app.engine.debts import debt_due_state, debt_remaining
from app.engine.money import Money, get_currency

CSV_DELIMITER = ";"
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_text(value: str | None) -> str:
    """Защита от CSV-инъекции: Excel исполняет ячейку, начинающуюся с «=»,
    «+», «-», «@». Текст из пользовательских полей экранируется апострофом
    (импорт его снимает — см. csv_import.unescape_text)."""
    if not value:
        return ""
    return f"'{value}" if value.startswith(_FORMULA_PREFIXES) else value


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return iso_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _major(minor: int, currency: str) -> str:
    return str(Money.of(minor, currency).to_decimal())


def write_csv(header: Sequence[str], rows: Iterable[Sequence[object]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=CSV_DELIMITER, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_cell(v) for v in row])
    return ("﻿" + buf.getvalue()).encode("utf-8")


TRANSACTION_HEADER = (
    "id",
    "occurred_at",
    "type",
    "amount_minor",
    "amount",
    "currency",
    "account_id",
    "account",
    "category_id",
    "category",
    "comment",
    "debt_id",
    "debt_name",
    "created_at",
)


def transactions_csv(db: Session) -> bytes:
    txs = db.scalars(select(Transaction).order_by(Transaction.occurred_at, Transaction.id))

    def rows():
        for t in txs:
            payment = t.debt_payment
            yield (
                t.id,
                t.occurred_at,
                t.type,
                t.amount_minor,
                _major(t.amount_minor, t.currency),
                t.currency,
                t.account_id,
                safe_text(t.account.name),
                t.category_id,
                safe_text(t.category.name),
                safe_text(t.comment),
                payment.debt_id if payment else None,
                safe_text(payment.debt.counterparty_name) if payment else None,
                t.created_at,
            )

    return write_csv(TRANSACTION_HEADER, rows())


def transfers_csv(db: Session) -> bytes:
    header = (
        "id",
        "occurred_at",
        "amount_minor",
        "amount",
        "currency",
        "from_account_id",
        "from_account",
        "to_account_id",
        "to_account",
        "comment",
        "created_at",
    )
    trs = db.scalars(select(Transfer).order_by(Transfer.occurred_at, Transfer.id))
    return write_csv(
        header,
        (
            (
                t.id,
                t.occurred_at,
                t.amount_minor,
                _major(t.amount_minor, t.currency),
                t.currency,
                t.from_account_id,
                safe_text(t.from_account.name),
                t.to_account_id,
                safe_text(t.to_account.name),
                safe_text(t.comment),
                t.created_at,
            )
            for t in trs
        ),
    )


def accounts_csv(db: Session) -> bytes:
    from app.api.v1.accounts import compute_balance

    header = ("id", "name", "type", "currency", "initial_balance_minor", "balance_minor", "balance", "is_active", "created_at")
    rows = []
    for a in db.scalars(select(Account).order_by(Account.id)):
        balance = compute_balance(db, a)
        rows.append(
            (
                a.id,
                safe_text(a.name),
                a.type,
                a.currency,
                a.initial_balance_minor,
                balance.minor,
                str(balance.to_decimal()),
                a.is_active,
                a.created_at,
            )
        )
    return write_csv(header, rows)


def debts_csv(db: Session) -> bytes:
    header = (
        "id",
        "counterparty",
        "direction",
        "currency",
        "principal_minor",
        "paid_minor",
        "remaining_minor",
        "due_date",
        "comment",
        "created_at",
        "due_state",
    )
    today = clock.today()
    rows = []
    for d in db.scalars(select(Debt).order_by(Debt.id)):
        cur = get_currency(d.currency)
        principal = Money.of(d.principal_minor, cur)
        remaining = debt_remaining(principal, [Money.of(p.amount_minor, cur) for p in d.payments])
        rows.append(
            (
                d.id,
                safe_text(d.counterparty_name),
                d.direction,
                d.currency,
                d.principal_minor,
                (principal - remaining).minor,
                remaining.minor,
                d.due_date,
                safe_text(d.comment),
                d.created_at,
                debt_due_state(d.due_date, remaining.minor, today).value,
            )
        )
    return write_csv(header, rows)


def goals_csv(db: Session) -> bytes:
    header = (
        "id",
        "name",
        "currency",
        "target_minor",
        "saved_minor",
        "target_date",
        "is_archived",
        "description",
        "created_at",
    )
    rows = []
    for g in db.scalars(select(Goal).order_by(Goal.id)):
        saved = sum(e.amount_minor if e.type == "contribution" else -e.amount_minor for e in g.entries)
        rows.append(
            (
                g.id,
                safe_text(g.name),
                g.currency,
                g.target_amount_minor,
                saved,
                g.target_date,
                g.is_archived,
                safe_text(g.description),
                g.created_at,
            )
        )
    return write_csv(header, rows)
