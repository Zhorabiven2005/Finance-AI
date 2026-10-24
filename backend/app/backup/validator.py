"""Проверка резервной копии ДО любых изменений БД.

Три уровня, каждый следующий выполняется только если пройден предыдущий:
  1. файл: размер, корректный JSON, формат Finance AI, поддерживаемая версия;
  2. схема: strict pydantic (типы, обязательные/неизвестные поля, диапазоны);
  3. смысл: уникальность id, внешние ключи, валюты, дерево категорий и
     инварианты предметной области (те же, что соблюдает API).

Модуль ничего не пишет в БД и вообще её не читает.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from pydantic import ValidationError

from app.backup.format import (
    BACKUP_FORMAT_NAME,
    MAX_BACKUP_BYTES,
    MAX_BACKUP_RECORDS,
    SECTION_LABELS,
    SUPPORTED_BACKUP_VERSIONS,
    BackupData,
    BackupDocument,
    BackupDocumentV1,
)
from app.engine.money import REGISTERED_CURRENCIES

MAX_REPORTED_ERRORS = 100

NOT_A_BACKUP = "Файл не является резервной копией Finance AI."
UNSUPPORTED_VERSION = "Эта версия резервной копии не поддерживается."


class BackupInvalidError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors[:3]))
        self.errors = errors[:MAX_REPORTED_ERRORS]
        self.total = len(errors)


_PYDANTIC_MESSAGES = {
    "missing": "обязательное поле отсутствует",
    "extra_forbidden": "неизвестное поле",
    "int_type": "ожидалось целое число",
    "int_parsing": "ожидалось целое число",
    "string_type": "ожидалась строка",
    "bool_type": "ожидалось true/false",
    "list_type": "ожидался список",
    "dict_type": "ожидался объект",
    "model_type": "ожидался объект",
    "literal_error": "недопустимое значение",
    "greater_than": "значение должно быть больше нуля",
    "greater_than_equal": "значение слишком маленькое",
    "less_than_equal": "значение слишком большое",
    "string_too_short": "пустая строка",
    "string_too_long": "строка слишком длинная",
    "timezone_aware": "дата и время должны содержать часовой пояс",
    "datetime_type": "некорректная дата и время",
    "datetime_parsing": "некорректная дата и время",
    "datetime_from_date_parsing": "некорректная дата и время",
    "date_type": "некорректная дата",
    "date_parsing": "некорректная дата (нужен формат ГГГГ-ММ-ДД)",
    "date_from_datetime_parsing": "некорректная дата (нужен формат ГГГГ-ММ-ДД)",
}


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in pairs]
    dupes = [k for k, n in Counter(keys).items() if n > 1]
    if dupes:
        raise ValueError(f"повторяющийся ключ «{dupes[0]}»")
    return dict(pairs)


def _load_json(raw: bytes) -> Any:
    if len(raw) > MAX_BACKUP_BYTES:
        raise BackupInvalidError(
            [f"Файл слишком большой: максимум {MAX_BACKUP_BYTES // (1024 * 1024)} МБ."]
        )
    if not raw.strip():
        raise BackupInvalidError(["Файл пуст."])
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise BackupInvalidError(["Файл повреждён: ожидалась кодировка UTF-8."]) from None
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as e:
        raise BackupInvalidError(
            [f"Файл повреждён: это не корректный JSON (строка {e.lineno}, позиция {e.colno})."]
        ) from None
    except ValueError as e:
        raise BackupInvalidError([f"Файл повреждён: {e}."]) from None
    except RecursionError:
        raise BackupInvalidError(["Файл повреждён: слишком глубокая вложенность JSON."]) from None


def _check_header(obj: Any) -> None:
    if not isinstance(obj, dict) or obj.get("format") != BACKUP_FORMAT_NAME:
        raise BackupInvalidError([NOT_A_BACKUP])
    version = obj.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise BackupInvalidError([f"{UNSUPPORTED_VERSION} Версия не указана или некорректна."])
    if version not in SUPPORTED_BACKUP_VERSIONS:
        raise BackupInvalidError([f"{UNSUPPORTED_VERSION} (версия {version})"])
    data = obj.get("data")
    if isinstance(data, dict):
        total = sum(len(v) for v in data.values() if isinstance(v, list))
        if total > MAX_BACKUP_RECORDS:
            raise BackupInvalidError(
                [f"Слишком много записей: {total}, максимум {MAX_BACKUP_RECORDS}."]
            )


def _schema_errors(obj: dict[str, Any], exc: ValidationError) -> list[str]:
    errors = []
    for err in exc.errors():
        loc = err["loc"]
        message = _PYDANTIC_MESSAGES.get(err["type"], err["msg"])
        if len(loc) >= 3 and loc[0] == "data" and isinstance(loc[2], int):
            section = str(loc[1])
            record_id = None
            try:
                record = obj["data"][section][loc[2]]
                if isinstance(record, dict):
                    record_id = record.get("id")
            except (KeyError, IndexError, TypeError):
                pass
            where = f"{SECTION_LABELS.get(section, section)}, запись №{loc[2] + 1}"
            if record_id is not None:
                where += f" (id={record_id})"
            field = ".".join(str(p) for p in loc[3:])
            errors.append(f"{where}, поле «{field}»: {message}" if field else f"{where}: {message}")
        else:
            field = ".".join(str(p) for p in loc) or "файл"
            errors.append(f"Поле «{field}»: {message}")
    return errors


def _semantic_errors(doc: BackupDocument) -> list[str]:
    d = doc.data
    errors: list[str] = []

    def err(section: str, record_id: int | None, message: str) -> None:
        prefix = SECTION_LABELS[section]
        errors.append(f"{prefix} (id={record_id}): {message}" if record_id is not None else f"{prefix}: {message}")

    # --- уникальность id ---
    for section in SECTION_LABELS:
        ids = [r.id for r in getattr(d, section)]
        for dup, n in Counter(ids).items():
            if n > 1:
                err(section, dup, f"id встречается {n} раза")

    def check_currency(section: str, record_id: int, code: str) -> None:
        if code not in REGISTERED_CURRENCIES:
            err(section, record_id, f"неизвестная валюта «{code}»")

    if doc.base_currency not in REGISTERED_CURRENCIES:
        errors.append(f"Неизвестная базовая валюта «{doc.base_currency}».")
    if doc.settings.base_currency != doc.base_currency:
        errors.append("Базовая валюта в настройках не совпадает с base_currency файла.")

    accounts = {a.id: a for a in d.accounts}
    categories = {c.id: c for c in d.categories}
    debts = {x.id: x for x in d.debts}
    payments = {p.id: p for p in d.debt_payments}
    transactions = {t.id: t for t in d.transactions}
    rules = {r.id: r for r in d.recurring_transactions}
    goals = {g.id: g for g in d.goals}

    for a in d.accounts:
        check_currency("accounts", a.id, a.currency)

    # --- категории: связи, типы, глубина не больше одного уровня ---
    names_by_type: dict[str, Counter[str]] = defaultdict(Counter)
    for c in d.categories:
        names_by_type[c.type][c.name.strip().casefold()] += 1
        if c.parent_id is None:
            continue
        if c.parent_id == c.id:
            err("categories", c.id, "категория не может быть родителем самой себя")
            continue
        parent = categories.get(c.parent_id)
        if parent is None:
            err("categories", c.id, f"родительская категория id={c.parent_id} не найдена")
            continue
        if parent.type != c.type:
            err("categories", c.id, "тип подкатегории не совпадает с типом родителя")
        if parent.parent_id is not None:
            err("categories", c.id, "вложенность больше одного уровня (или цикл в дереве категорий)")
    for type_, counter in names_by_type.items():
        for name, n in counter.items():
            if n > 1:
                errors.append(f"Категории: название «{name}» ({type_}) повторяется {n} раза")

    # --- долги и платежи ---
    for x in d.debts:
        check_currency("debts", x.id, x.currency)
    paid_by_debt: Counter[int] = Counter()
    for p in d.debt_payments:
        debt = debts.get(p.debt_id)
        if debt is None:
            err("debt_payments", p.id, f"долг id={p.debt_id} не найден")
            continue
        paid_by_debt[debt.id] += p.amount_minor
        if p.account_id is not None:
            account = accounts.get(p.account_id)
            if account is None:
                err("debt_payments", p.id, f"счёт id={p.account_id} не найден")
            elif account.currency != debt.currency:
                err("debt_payments", p.id, "валюта счёта не совпадает с валютой долга")
    for debt_id, paid in paid_by_debt.items():
        if paid > debts[debt_id].principal_minor:
            err("debts", debt_id, "сумма платежей больше суммы долга")

    # --- операции ---
    ledger_by_payment: Counter[int] = Counter()
    for t in d.transactions:
        account = accounts.get(t.account_id)
        category = categories.get(t.category_id)
        if account is None:
            err("transactions", t.id, f"счёт id={t.account_id} не найден")
        elif t.currency != account.currency:
            err("transactions", t.id, "валюта операции не совпадает с валютой счёта")
        if category is None:
            err("transactions", t.id, f"категория id={t.category_id} не найдена")
        elif category.type != t.type:
            err("transactions", t.id, "тип операции не совпадает с типом категории")
        check_currency("transactions", t.id, t.currency)
        if t.debt_payment_id is not None:
            ledger_by_payment[t.debt_payment_id] += 1
            payment = payments.get(t.debt_payment_id)
            if payment is None:
                err("transactions", t.id, f"платёж по долгу id={t.debt_payment_id} не найден")
                continue
            debt = debts.get(payment.debt_id)
            expected_type = "expense" if debt and debt.direction == "i_owe" else "income"
            if payment.account_id != t.account_id:
                err("transactions", t.id, "счёт операции не совпадает со счётом платежа по долгу")
            if payment.amount_minor != t.amount_minor:
                err("transactions", t.id, "сумма операции не совпадает с суммой платежа по долгу")
            if debt is not None and t.type != expected_type:
                err("transactions", t.id, "тип операции не соответствует направлению долга")
    # Инвариант «платёж со счётом = ровно одна операция в журнале».
    for p in d.debt_payments:
        n = ledger_by_payment.get(p.id, 0)
        if p.account_id is not None and n != 1:
            err("debt_payments", p.id, "у платежа со счётом должна быть ровно одна связанная операция")
        if p.account_id is None and n:
            err("debt_payments", p.id, "у платежа без счёта не может быть связанной операции")

    # --- переводы ---
    for tr in d.transfers:
        src, dst = accounts.get(tr.from_account_id), accounts.get(tr.to_account_id)
        if tr.from_account_id == tr.to_account_id:
            err("transfers", tr.id, "счёт списания и зачисления совпадают")
        if src is None:
            err("transfers", tr.id, f"счёт id={tr.from_account_id} не найден")
        if dst is None:
            err("transfers", tr.id, f"счёт id={tr.to_account_id} не найден")
        if src and dst and not (src.currency == dst.currency == tr.currency):
            err("transfers", tr.id, "валюты перевода и счетов не совпадают")

    # --- бюджеты ---
    seen_periods: Counter[tuple[int, int, int, str]] = Counter()
    for b in d.budgets:
        check_currency("budgets", b.id, b.currency)
        category = categories.get(b.category_id)
        if category is None:
            err("budgets", b.id, f"категория id={b.category_id} не найдена")
        elif category.type != "expense":
            err("budgets", b.id, "бюджет можно задать только для категории расходов")
        seen_periods[(b.category_id, b.year, b.month, b.currency)] += 1
    for (cid, year, month, cur), n in seen_periods.items():
        if n > 1:
            errors.append(f"Бюджеты: категория id={cid} за {month:02d}.{year} ({cur}) задана {n} раза")

    # --- регулярные операции и их запуски ---
    for r in d.recurring_transactions:
        account = accounts.get(r.account_id)
        category = categories.get(r.category_id)
        if account is None:
            err("recurring_transactions", r.id, f"счёт id={r.account_id} не найден")
        elif r.currency != account.currency:
            err("recurring_transactions", r.id, "валюта не совпадает с валютой счёта")
        if category is None:
            err("recurring_transactions", r.id, f"категория id={r.category_id} не найдена")
        elif category.type != r.type:
            err("recurring_transactions", r.id, "тип не совпадает с типом категории")
        if r.end_date is not None and r.end_date < r.start_date:
            err("recurring_transactions", r.id, "дата окончания раньше даты начала")
        if r.next_run_date < r.start_date:
            err("recurring_transactions", r.id, "дата следующей операции раньше даты начала")
    run_keys: Counter[tuple[int, Any]] = Counter()
    for run in d.recurring_transaction_runs:
        if run.recurring_transaction_id not in rules:
            err("recurring_transaction_runs", run.id, f"регулярная операция id={run.recurring_transaction_id} не найдена")
        if run.transaction_id not in transactions:
            err("recurring_transaction_runs", run.id, f"операция id={run.transaction_id} не найдена")
        run_keys[(run.recurring_transaction_id, run.run_date)] += 1
    for (rid, run_date), n in run_keys.items():
        if n > 1:
            errors.append(f"Запуски регулярных операций: правило id={rid} за {run_date} повторяется {n} раза")

    # --- цели ---
    saved: Counter[int] = Counter()
    for g in d.goals:
        check_currency("goals", g.id, g.currency)
    for e in d.goal_entries:
        if e.goal_id not in goals:
            err("goal_entries", e.id, f"цель id={e.goal_id} не найдена")
            continue
        saved[e.goal_id] += e.amount_minor if e.type == "contribution" else -e.amount_minor
    for goal_id, amount in saved.items():
        if amount < 0:
            err("goals", goal_id, "списаний больше, чем накоплено")

    # --- уведомления (version 2) ---
    for key, n in Counter(x.dedup_key for x in d.notifications).items():
        if n > 1:
            errors.append(f"Уведомления: ключ «{key}» повторяется {n} раза")
    for x in d.notifications:
        if x.data is not None:
            try:
                parsed = json.loads(x.data)
            except ValueError:
                parsed = None
            if not isinstance(parsed, dict):
                err("notifications", x.id, "поле data должно быть JSON-объектом")
        # Ссылка на сущность мягкая (без внешнего ключа): уведомление может
        # пережить удаление долга, поэтому её отсутствие — не ошибка.

    if not any(getattr(d, s) for s in SECTION_LABELS):
        errors.append("Резервная копия пуста — в ней нет ни одной записи.")
    return errors


def validate_backup(raw: bytes) -> BackupDocument:
    """Возвращает проверенный документ или бросает BackupInvalidError со
    списком понятных пользователю ошибок. Ничего не пишет в БД."""
    obj = _load_json(raw)
    _check_header(obj)
    text = raw.decode("utf-8-sig")
    try:
        if obj["version"] == 1:
            doc = _upgrade_v1(BackupDocumentV1.model_validate_json(text, strict=True))
        else:
            doc = BackupDocument.model_validate_json(text, strict=True)
    except ValidationError as e:
        raise BackupInvalidError(_schema_errors(obj, e)) from None
    errors = _semantic_errors(doc)
    if errors:
        raise BackupInvalidError(errors)
    return doc


def _upgrade_v1(doc: BackupDocumentV1) -> BackupDocument:
    """Version 1 -> текущая модель: всё то же, уведомлений нет. Документ уже
    прошёл строгую проверку схемы v1, поэтому повторная проверка не нужна."""
    data = BackupData.model_construct(
        **{name: getattr(doc.data, name) for name in type(doc.data).model_fields}, notifications=[]
    )
    return BackupDocument.model_construct(
        format=doc.format,
        version=1,
        exported_at=doc.exported_at,
        base_currency=doc.base_currency,
        settings=doc.settings,
        data=data,
    )


def summarize(doc: BackupDocument) -> dict[str, int]:
    return {section: len(getattr(doc.data, section)) for section in SECTION_LABELS}
