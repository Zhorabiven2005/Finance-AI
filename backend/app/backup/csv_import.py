"""Импорт операций (доходов и расходов) из CSV.

Двухшаговый и безопасный:
  * build_plan — разбор, сопоставление колонок, проверка каждой строки,
    поиск дублей. НИЧЕГО не пишет в БД; результат — preview для пользователя;
  * commit_plan — вызывается с тем же файлом и теми же решениями; план
    строится ЗАНОВО (клиенту не доверяем) и записывается одной транзакцией,
    только если в нём нет ни одной ошибки. Частичного импорта не бывает.

Счета и категории, которых нет в БД, никогда не создаются молча: строка с
неизвестным названием — ошибка, пока пользователь явно не выберет
«сопоставить с существующим» или «создать новый».

Дубли: отпечаток операции = (счёт, тип, сумма в минорных единицах, момент
времени в UTC, категория, нормализованный комментарий). Сравниваются
мультимножества: если в файле две одинаковые покупки, а в БД уже есть одна,
импортируется ровно одна. Повторный импорт того же файла даёт 0 новых.
"""

from __future__ import annotations

import base64
import binascii
import csv
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Account, Category, Transaction
from app.db.models.app_settings import get_base_currency
from app.engine.money import REGISTERED_CURRENCIES, get_currency

MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_CSV_ROWS = 10_000
MAX_CSV_COLUMNS = 50
MAX_FIELD_CHARS = 10_000
MAX_REPORTED_ERRORS = 200
SAMPLE_ROWS = 20

FieldKey = Literal["occurred_at", "amount", "amount_minor", "type", "account", "category", "comment", "currency"]

FIELD_LABELS: dict[str, str] = {
    "occurred_at": "Дата",
    "amount": "Сумма",
    "amount_minor": "Сумма в минорных единицах",
    "type": "Тип (доход/расход)",
    "account": "Счёт",
    "category": "Категория",
    "comment": "Комментарий",
    "currency": "Валюта",
}

_SYNONYMS: dict[str, set[str]] = {
    "occurred_at": {"occurred_at", "date", "datetime", "дата", "дата операции", "дата и время", "время операции"},
    "amount": {"amount", "sum", "сумма", "сумма операции"},
    "amount_minor": {"amount_minor"},
    "type": {"type", "тип", "тип операции", "вид операции"},
    "account": {"account", "account_name", "счёт", "счет", "карта"},
    "category": {"category", "category_name", "категория"},
    "comment": {"comment", "комментарий", "описание", "description", "примечание", "назначение платежа"},
    "currency": {"currency", "валюта"},
}

_TYPE_WORDS = {
    "income": "income",
    "доход": "income",
    "доходы": "income",
    "приход": "income",
    "зачисление": "income",
    "expense": "expense",
    "расход": "expense",
    "расходы": "expense",
    "списание": "expense",
}

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?)?(?:Z|[+-]\d{2}:?\d{2})?$"
)
_RU_DATE_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})(?: (\d{2}):(\d{2})(?::(\d{2}))?)?$")
_AMOUNT_RE = re.compile(r"^\d+(?:[.,]\d+)?$")


class CsvImportFileError(Exception):
    """Файл целиком непригоден (не CSV, слишком большой, нет заголовка)."""


class Resolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["map", "create"]
    target_id: int | None = None


class CsvImportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mapping: dict[FieldKey, str | None] | None = None
    default_account_id: int | None = None
    # Значение Date.getTimezoneOffset() браузера: время без часового пояса в
    # файле трактуется как местное время пользователя.
    tz_offset_minutes: int = Field(default=0, ge=-840, le=840)
    account_resolutions: dict[str, Resolution] = Field(default_factory=dict)
    category_resolutions: dict[str, Resolution] = Field(default_factory=dict)


class CsvImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_base64: str = Field(max_length=(MAX_CSV_BYTES * 4) // 3 + 16)
    options: CsvImportOptions = Field(default_factory=CsvImportOptions)
    # Для commit — явное подтверждение пользователя; preview его игнорирует.
    confirm: bool = False


def unescape_text(value: str) -> str:
    if len(value) > 1 and value[0] == "'" and value[1] in "=+-@\t\r":
        return value[1:]
    return value


def norm_name(value: str) -> str:
    return " ".join(value.split()).casefold()


def _norm_comment(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


# ---------------------------------------------------------------------------
# Разбор значений
# ---------------------------------------------------------------------------


def parse_amount_minor_text(text: str, currency: str) -> int:
    """'1 234,56 ₽' -> 123456 (со знаком). Без float: Decimal и проверка
    точности валюты (лишние знаки после запятой — ошибка, а не округление)."""
    cur = get_currency(currency)
    s = text.strip().replace("−", "-")
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    for c in REGISTERED_CURRENCIES.values():
        s = s.replace(c.symbol, "")
        s = re.sub(re.escape(c.code), "", s, flags=re.IGNORECASE)
    s = re.sub(r"(?i)руб\.?", "", s)
    s = re.sub(r"[\s  ']", "", s)
    if s.startswith("+"):
        s = s[1:]
    elif s.startswith("-"):
        negative, s = not negative, s[1:]
    if not _AMOUNT_RE.match(s):
        raise ValueError(f"некорректная сумма «{text.strip()}»")
    try:
        dec = Decimal(s.replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"некорректная сумма «{text.strip()}»") from None
    exponent = dec.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > cur.exponent:
        raise ValueError(
            f"сумма «{text.strip()}»: больше знаков после запятой, чем допускает {cur.code}"
        )
    minor = int(dec * cur.subunit)
    return -minor if negative else minor


def parse_minor_int(text: str) -> int:
    s = text.strip().replace("−", "-")
    if not re.fullmatch(r"[+-]?\d+", s):
        raise ValueError(f"некорректная сумма в минорных единицах «{text.strip()}»")
    return int(s)


def parse_datetime_text(text: str, tz_offset_minutes: int) -> datetime:
    """Возвращает aware-UTC. Дата без времени — 12:00 местного времени, чтобы
    операция не уехала на соседние сутки из-за часового пояса."""
    s = text.strip()
    local_tz = timezone(-timedelta(minutes=tz_offset_minutes))
    if _ISO_RE.match(s):
        try:
            parsed = datetime.fromisoformat(s)
        except ValueError:
            raise ValueError(f"некорректная дата «{s}»") from None
        if len(s) == 10:
            parsed = datetime.combine(parsed.date(), time(12, 0))
    else:
        m = _RU_DATE_RE.match(s)
        if not m:
            raise ValueError(
                f"неизвестный или неоднозначный формат даты «{s}» "
                "(используйте ГГГГ-ММ-ДД, ГГГГ-ММ-ДД ЧЧ:ММ:СС, ISO 8601 или ДД.ММ.ГГГГ)"
            )
        day, month, year, hh, mm, ss = m.groups()
        try:
            parsed = datetime(
                int(year), int(month), int(day),
                int(hh) if hh else 12, int(mm) if mm else 0, int(ss) if ss else 0,
            )
        except ValueError:
            raise ValueError(f"некорректная дата «{s}»") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_tz)
    return parsed.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Файл
# ---------------------------------------------------------------------------


def decode_upload(file_base64: str) -> bytes:
    try:
        raw = base64.b64decode(file_base64, validate=True)
    except (binascii.Error, ValueError):
        raise CsvImportFileError("Файл повреждён: не удалось прочитать содержимое.") from None
    if len(raw) > MAX_CSV_BYTES:
        raise CsvImportFileError(f"Файл слишком большой: максимум {MAX_CSV_BYTES // (1024 * 1024)} МБ.")
    return raw


def _decode_text(raw: bytes) -> tuple[str, str]:
    if b"\x00" in raw:
        raise CsvImportFileError("Это не текстовый CSV-файл.")
    try:
        return raw.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp1251"), "windows-1251"


def _read_table(raw: bytes) -> tuple[str, str, list[str], list[list[str]]]:
    text, encoding = _decode_text(raw)
    if not text.strip():
        raise CsvImportFileError("Файл пуст.")
    first_line = text.splitlines()[0]
    delimiter = max(";,\t", key=first_line.count)
    if first_line.count(delimiter) == 0:
        raise CsvImportFileError("Не удалось определить разделитель колонок (ожидается «;», «,» или табуляция).")
    csv.field_size_limit(MAX_FIELD_CHARS)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        header = [h.strip() for h in next(reader)]
        rows: list[list[str]] = []
        for row in reader:
            if len(rows) >= MAX_CSV_ROWS:
                raise CsvImportFileError(f"Слишком много строк: максимум {MAX_CSV_ROWS}.")
            rows.append(row)
    except csv.Error as e:
        raise CsvImportFileError(f"Файл повреждён: {e}.") from None
    if len(header) > MAX_CSV_COLUMNS:
        raise CsvImportFileError(f"Слишком много колонок: максимум {MAX_CSV_COLUMNS}.")
    if not any(header):
        raise CsvImportFileError("В первой строке должны быть названия колонок.")
    dupes = [h for h, n in Counter(h for h in header if h).items() if n > 1]
    if dupes:
        raise CsvImportFileError(f"Колонка «{dupes[0]}» встречается в заголовке несколько раз.")
    return encoding, delimiter, header, rows


def suggest_mapping(header: list[str]) -> dict[str, str | None]:
    mapping: dict[str, str | None] = {k: None for k in FIELD_LABELS}
    for h in header:
        key = norm_name(h)
        for field_key, names in _SYNONYMS.items():
            if key in names and mapping[field_key] is None:
                mapping[field_key] = h
    # Из нашего же экспорта есть и amount, и amount_minor: точнее — целое.
    if mapping["amount_minor"]:
        mapping["amount"] = None
    return mapping


# ---------------------------------------------------------------------------
# План импорта
# ---------------------------------------------------------------------------


@dataclass
class ParsedRow:
    row: int
    status: str = "new"  # new | duplicate | skipped | error
    errors: list[str] = field(default_factory=list)
    occurred_at: datetime | None = None
    type: str | None = None
    amount_minor: int | None = None
    currency: str | None = None
    account_name: str | None = None
    account_id: int | None = None
    account_key: str | None = None
    category_name: str | None = None
    category_id: int | None = None
    category_key: str | None = None
    comment: str | None = None


@dataclass
class ImportPlan:
    encoding: str
    delimiter: str
    header: list[str]
    mapping: dict[str, str | None]
    suggested_mapping: dict[str, str | None]
    mapping_errors: list[str]
    rows: list[ParsedRow]
    unknown_accounts: list[dict]
    unknown_categories: list[dict]
    new_accounts: dict[str, dict]
    new_categories: dict[str, dict]

    @property
    def errors(self) -> list[dict]:
        return [{"row": r.row, "message": m} for r in self.rows for m in r.errors]

    def count(self, status: str) -> int:
        return sum(1 for r in self.rows if r.status == status)

    @property
    def can_import(self) -> bool:
        return not self.mapping_errors and self.count("error") == 0 and self.count("new") > 0


def _cat_key(type_: str, name: str) -> str:
    return f"{type_}:{norm_name(name)}"


def build_plan(db: Session, raw: bytes, options: CsvImportOptions) -> ImportPlan:
    encoding, delimiter, header, table = _read_table(raw)
    suggested = suggest_mapping(header)
    mapping: dict[str, str | None] = {k: None for k in FIELD_LABELS}
    source = options.mapping if options.mapping is not None else suggested
    for k, v in source.items():
        mapping[k] = v or None

    mapping_errors: list[str] = []
    for k, col in mapping.items():
        if col is not None and col not in header:
            mapping_errors.append(f"Колонка «{col}» для поля «{FIELD_LABELS[k]}» не найдена в файле.")
    if not mapping["occurred_at"]:
        mapping_errors.append("Не сопоставлено обязательное поле «Дата».")
    if not mapping["amount"] and not mapping["amount_minor"]:
        mapping_errors.append("Не сопоставлено обязательное поле «Сумма».")
    if mapping["amount"] and mapping["amount_minor"]:
        mapping_errors.append("Сопоставьте только одно из полей «Сумма» и «Сумма в минорных единицах».")
    if not mapping["category"]:
        mapping_errors.append("Не сопоставлено обязательное поле «Категория».")

    default_account: Account | None = None
    if options.default_account_id is not None:
        default_account = db.get(Account, options.default_account_id)
        if default_account is None:
            mapping_errors.append("Выбранный счёт по умолчанию не найден.")
    if not mapping["account"] and default_account is None:
        mapping_errors.append("Не сопоставлено поле «Счёт» и не выбран счёт для всех строк.")

    base_currency = get_base_currency(db)
    accounts = {norm_name(a.name): a for a in db.scalars(select(Account))}
    accounts_by_id = {a.id: a for a in accounts.values()}
    categories = {_cat_key(c.type, c.name): c for c in db.scalars(select(Category))}
    categories_by_id = {c.id: c for c in categories.values()}
    names_any_type = {norm_name(c.name): c for c in categories.values()}

    col_index = {h: i for i, h in enumerate(header)}
    debt_col = col_index.get("debt_id")
    rows: list[ParsedRow] = []

    if not mapping_errors:
        for i, values in enumerate(table):
            row_no = i + 2
            if not any(v.strip() for v in values):
                continue
            pr = ParsedRow(row=row_no)
            rows.append(pr)

            def get(field_key: str) -> str:
                col = mapping[field_key]
                if col is None:
                    return ""
                idx = col_index[col]
                return unescape_text(values[idx].strip()) if idx < len(values) else ""

            if debt_col is not None and debt_col < len(values) and values[debt_col].strip():
                pr.status = "skipped"
                pr.errors = []
                continue

            # --- валюта и счёт ---
            currency_text = get("currency").upper()
            if currency_text and currency_text not in REGISTERED_CURRENCIES:
                pr.errors.append(f"неизвестная валюта «{currency_text}»")
            account_name = get("account") if mapping["account"] else ""
            account: Account | None = None
            if account_name:
                pr.account_name = account_name
                key = norm_name(account_name)
                account = accounts.get(key)
                if account is None:
                    resolution = options.account_resolutions.get(key)
                    if resolution and resolution.action == "map":
                        account = accounts_by_id.get(resolution.target_id or -1)
                        if account is None:
                            pr.errors.append(f"счёт для сопоставления с «{account_name}» не найден")
                    elif resolution and resolution.action == "create":
                        pr.account_key = key
                    else:
                        pr.errors.append(f"счёт «{account_name}» не найден")
                        pr.account_key = key
            elif default_account is not None:
                account = default_account
                pr.account_name = account.name
            else:
                pr.errors.append("не указан счёт")

            if account is not None:
                pr.account_id = account.id
                pr.currency = account.currency
                if currency_text and currency_text != account.currency:
                    pr.errors.append(
                        f"валюта {currency_text} не совпадает с валютой счёта «{account.name}» ({account.currency})"
                    )
            else:
                pr.currency = currency_text or base_currency

            # --- сумма и тип ---
            currency_for_amount = pr.currency if pr.currency in REGISTERED_CURRENCIES else base_currency
            amount_text = get("amount_minor") if mapping["amount_minor"] else get("amount")
            signed: int | None = None
            if not amount_text:
                pr.errors.append("не указана сумма")
            else:
                try:
                    signed = (
                        parse_minor_int(amount_text)
                        if mapping["amount_minor"]
                        else parse_amount_minor_text(amount_text, currency_for_amount)
                    )
                    if signed == 0:
                        pr.errors.append("сумма не может быть нулевой")
                        signed = None
                except ValueError as e:
                    pr.errors.append(str(e))

            type_text = get("type") if mapping["type"] else ""
            if type_text:
                pr.type = _TYPE_WORDS.get(norm_name(type_text))
                if pr.type is None:
                    pr.errors.append(f"неизвестный тип операции «{type_text}» (ожидается доход/расход)")
                elif signed is not None and signed < 0 and pr.type == "income":
                    pr.errors.append("отрицательная сумма у дохода")
            elif signed is not None:
                pr.type = "income" if signed > 0 else "expense"
            if signed is not None:
                pr.amount_minor = abs(signed)

            # --- дата ---
            date_text = get("occurred_at")
            if not date_text:
                pr.errors.append("не указана дата")
            else:
                try:
                    pr.occurred_at = parse_datetime_text(date_text, options.tz_offset_minutes)
                except ValueError as e:
                    pr.errors.append(str(e))

            # --- категория ---
            category_name = get("category")
            if not category_name:
                pr.errors.append("не указана категория")
            elif pr.type is not None:
                pr.category_name = category_name
                key = _cat_key(pr.type, category_name)
                category = categories.get(key)
                if category is None:
                    resolution = options.category_resolutions.get(key)
                    other = names_any_type.get(norm_name(category_name))
                    if resolution and resolution.action == "map":
                        category = categories_by_id.get(resolution.target_id or -1)
                        if category is None:
                            pr.errors.append(f"категория для сопоставления с «{category_name}» не найдена")
                        elif category.type != pr.type:
                            pr.errors.append(f"категория «{category.name}» другого типа")
                            category = None
                    elif resolution and resolution.action == "create":
                        pr.category_key = key
                    elif other is not None:
                        kind = "доходов" if other.type == "income" else "расходов"
                        pr.errors.append(f"категория «{category_name}» — это категория {kind}")
                    else:
                        pr.errors.append(f"категория «{category_name}» не найдена")
                        pr.category_key = key
                if category is not None:
                    pr.category_id = category.id

            comment = get("comment")
            if len(comment) > 500:
                pr.errors.append("комментарий длиннее 500 символов")
            pr.comment = comment or None

            if pr.errors:
                pr.status = "error"

    # --- неизвестные счета и категории (для решений пользователя) ---
    unknown_accounts: dict[str, dict] = {}
    unknown_categories: dict[str, dict] = {}
    new_accounts: dict[str, dict] = {}
    new_categories: dict[str, dict] = {}
    for r in rows:
        if r.account_key:
            acc = unknown_accounts.setdefault(
                r.account_key, {"key": r.account_key, "name": r.account_name, "rows": 0, "currencies": set()}
            )
            acc["rows"] += 1
            acc["currencies"].add(r.currency)
            res = options.account_resolutions.get(r.account_key)
            if res and res.action == "create":
                new_accounts.setdefault(r.account_key, {"name": r.account_name, "currencies": set()})["currencies"].add(r.currency)
        if r.category_key:
            cat = unknown_categories.setdefault(
                r.category_key, {"key": r.category_key, "name": r.category_name, "type": r.type, "rows": 0}
            )
            cat["rows"] += 1
            res = options.category_resolutions.get(r.category_key)
            if res and res.action == "create":
                new_categories[r.category_key] = {"name": r.category_name, "type": r.type}
    for key, acc in new_accounts.items():
        currencies = acc.pop("currencies")
        if len(currencies) > 1:
            for r in rows:
                if r.account_key == key:
                    r.errors.append(f"у нового счёта «{acc['name']}» в файле несколько валют")
                    r.status = "error"
        acc["currency"] = next(iter(currencies))
    for acc in unknown_accounts.values():
        acc["currencies"] = sorted(acc["currencies"])

    _mark_duplicates(db, rows)
    return ImportPlan(
        encoding=encoding,
        delimiter=delimiter,
        header=header,
        mapping=mapping,
        suggested_mapping=suggested,
        mapping_errors=mapping_errors,
        rows=rows,
        unknown_accounts=list(unknown_accounts.values()),
        unknown_categories=list(unknown_categories.values()),
        new_accounts=new_accounts,
        new_categories=new_categories,
    )


def _fingerprint(account_id, type_, amount_minor, occurred_at, category_id, comment) -> tuple:
    return (
        account_id,
        type_,
        amount_minor,
        occurred_at.astimezone(timezone.utc).replace(microsecond=0),
        category_id,
        _norm_comment(comment),
    )


def _mark_duplicates(db: Session, rows: list[ParsedRow]) -> None:
    candidates = [
        r for r in rows if r.status == "new" and r.account_id is not None and r.category_id is not None
    ]
    if not candidates:
        return
    account_ids = {r.account_id for r in candidates}
    start = min(r.occurred_at for r in candidates if r.occurred_at) - timedelta(seconds=1)
    end = max(r.occurred_at for r in candidates if r.occurred_at) + timedelta(seconds=1)
    existing = Counter(
        _fingerprint(t.account_id, t.type, t.amount_minor, t.occurred_at, t.category_id, t.comment)
        for t in db.scalars(
            select(Transaction).where(
                Transaction.account_id.in_(account_ids),
                Transaction.occurred_at >= start,
                Transaction.occurred_at <= end,
            )
        )
    )
    for r in candidates:
        fp = _fingerprint(r.account_id, r.type, r.amount_minor, r.occurred_at, r.category_id, r.comment)
        if existing[fp] > 0:
            existing[fp] -= 1
            r.status = "duplicate"


def plan_to_dict(plan: ImportPlan) -> dict:
    errors = plan.errors
    sample = []
    for r in plan.rows[:SAMPLE_ROWS]:
        sample.append(
            {
                "row": r.row,
                "status": r.status,
                "occurred_at": r.occurred_at.isoformat().replace("+00:00", "Z") if r.occurred_at else None,
                "type": r.type,
                "amount_minor": r.amount_minor,
                "currency": r.currency,
                "account": r.account_name,
                "category": r.category_name,
                "comment": r.comment,
            }
        )
    return {
        "encoding": plan.encoding,
        "delimiter": plan.delimiter,
        "headers": plan.header,
        "fields": [
            {"key": k, "label": v, "required": k in ("occurred_at", "amount", "category")}
            for k, v in FIELD_LABELS.items()
        ],
        "mapping": plan.mapping,
        "suggested_mapping": plan.suggested_mapping,
        "mapping_errors": plan.mapping_errors,
        "total_rows": len(plan.rows),
        "new_rows": plan.count("new"),
        "duplicate_rows": plan.count("duplicate"),
        "skipped_rows": plan.count("skipped"),
        "error_rows": plan.count("error"),
        "errors": errors[:MAX_REPORTED_ERRORS],
        "errors_total": len(errors),
        "unknown_accounts": plan.unknown_accounts,
        "unknown_categories": plan.unknown_categories,
        "new_accounts": list(plan.new_accounts.values()),
        "new_categories": list(plan.new_categories.values()),
        "sample": sample,
        "can_import": plan.can_import,
    }


def commit_plan(db: Session, plan: ImportPlan) -> dict:
    """Пишет план одной транзакцией. Вызывать только при plan.can_import."""
    if not plan.can_import:
        raise ValueError("план импорта содержит ошибки")
    try:
        created_accounts: dict[str, int] = {}
        for key, acc in plan.new_accounts.items():
            account = Account(
                name=acc["name"], type="bank", currency=acc["currency"], initial_balance_minor=0, is_active=True
            )
            db.add(account)
            db.flush()
            created_accounts[key] = account.id
        created_categories: dict[str, int] = {}
        for key, cat in plan.new_categories.items():
            category = Category(name=cat["name"], type=cat["type"], is_default=False, is_archived=False)
            db.add(category)
            db.flush()
            created_categories[key] = category.id

        created = 0
        for r in plan.rows:
            if r.status != "new":
                continue
            account_id = r.account_id or created_accounts[r.account_key]  # type: ignore[index]
            category_id = r.category_id or created_categories[r.category_key]  # type: ignore[index]
            currency = r.currency
            if r.account_id is None:
                currency = plan.new_accounts[r.account_key]["currency"]  # type: ignore[index]
            db.add(
                Transaction(
                    account_id=account_id,
                    category_id=category_id,
                    type=r.type,
                    amount_minor=r.amount_minor,
                    currency=currency,
                    occurred_at=r.occurred_at,
                    comment=r.comment,
                )
            )
            created += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "created": created,
        "duplicates_skipped": plan.count("duplicate"),
        "skipped": plan.count("skipped"),
        "created_accounts": len(plan.new_accounts),
        "created_categories": len(plan.new_categories),
    }
