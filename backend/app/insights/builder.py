"""Сборка финансовых инсайтов (Stage 3C).

Только чтение (сессия get_readonly_db). Все числа считаются здесь и в
app/engine/* детерминированно; бюджеты, цели и особенности данных берутся из
финансового контекста Stage 2F (build_context), чтобы цифры совпадали с
экранами приложения, а не считались второй раз по-другому.

Денежные правила:
  * суммы — целые minor-единицы (Money), по каждой валюте отдельно; разные
    валюты не складываются и не конвертируются;
  * доходы и расходы — только операции (Transaction); переводы между своими
    счетами (Transfer) в них не входят и показываются отдельно;
  * изменение остатка за период считается из движений по активным счетам
    (операции и переводы), а не из текущего баланса;
  * погашения долгов — обычные операции модели (категории «Погашение долга»
    и «Возврат долга»): входят в поток, но названы отдельной строкой;
  * возвратов как отдельного типа в модели нет: возврат покупки — доход.

Комментарии к операциям (описания платежей) сюда не попадают: в инсайте
есть только очищенные названия категорий и счетов.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.assistant.digest import QUALITY_TEXT
from app.context import builder as context_builder
from app.context.indicators import round_percent
from app.context.labels import sanitize_label
from app.db.models import Account, Category, RecurringTransaction, Transaction, Transfer
from app.engine import insights as rules
from app.engine.analytics import share_percent
from app.engine.flows import debt_repayment_category_ids, flow_kind, is_transfer
from app.engine.budgets import month_bounds
from app.engine.money import Money, money_sum
from app.insights.comparison import build_comparison
from app.notifications.rules import previous_month
from app.schemas.insights import (
    InsightItemOut,
    InsightLinkOut,
    InsightMetricOut,
    InsightOut,
    InsightPeriodKey,
    InsightPeriodOut,
    InsightsOut,
    UnavailableInsightOut,
)
from app.schemas.money import MoneyOut

MONTHS_RU = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
TOP_CATEGORIES = 5
TOP_LARGE_EXPENSES = 3
MAX_RECURRING_ITEMS = 5
MAX_BUDGET_ITEMS = 5
MAX_GOAL_ITEMS = 5
# Окно «обычного уровня» трат и поиска регулярных платежей — полгода до
# конца периода.
HISTORY_WINDOW_DAYS = 183
# Регулярность ищется, только если история охватывает хотя бы два месяца.
RECURRING_MIN_HISTORY_DAYS = 60
# Доля «прочих» операций, начиная с которой структура считается ненадёжной.
OTHER_CATEGORY_SHARE_WARNING = 25
OTHER_CATEGORY_NAMES = {"expense": "Прочие расходы", "income": "Прочие доходы"}
SEVERITY_ORDER = {"warning": 0, "attention": 1, "info": 2}
TYPE_ORDER = ["budgets", "cash_flow", "large_expenses", "spending_structure", "recurring_expenses", "goals", "data_quality"]


# --- период --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Period:
    key: InsightPeriodKey
    start: datetime
    end: datetime
    complete: bool
    label: str

    def out(self) -> InsightPeriodOut:
        return InsightPeriodOut(
            key=self.key, date_from=self.start.date(), date_to=self.end.date(), label=self.label, complete=self.complete
        )


def resolve_period(key: InsightPeriodKey, today: date) -> _Period:
    """Календарные месяцы в UTC — те же границы, что у бюджетов и контекста."""
    if key == "current_month":
        start, end = month_bounds(today.year, today.month)
        return _Period(key, start, end, False, f"{MONTHS_RU[today.month - 1]} {today.year} (месяц ещё идёт)")
    if key == "previous_month":
        y, m = previous_month(today.year, today.month)
        start, end = month_bounds(y, m)
        return _Period(key, start, end, True, f"{MONTHS_RU[m - 1]} {y}")
    months = []
    y, m = today.year, today.month
    for _ in range(3):
        y, m = previous_month(y, m)
        months.append((y, m))
    (y1, m1), (y3, m3) = months[-1], months[0]
    start, _ = month_bounds(y1, m1)
    _, end = month_bounds(y3, m3)
    label = f"{MONTHS_RU[m1 - 1]} {y1} — {MONTHS_RU[m3 - 1]} {y3} (3 полных месяца)"
    return _Period("last_3_months", start, end, True, label)


# --- форматирование ---------------------------------------------------------------------


def _out(m: Money) -> MoneyOut:
    return MoneyOut(minor=m.minor, currency=m.currency.code)


def _fmt(m: Money) -> str:
    return m.format()


def _pct(value: float) -> str:
    return f"{value:.1f}".replace(".", ",") + "%"


def _d(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _label(raw: str | None) -> str:
    return sanitize_label(raw)[0] or "—"


def _utc_date(at: datetime) -> date:
    return at.astimezone(timezone.utc).date()


# --- сборка ---------------------------------------------------------------------------------


@dataclass
class _Data:
    period: _Period
    today: date
    now: datetime
    txs: list[Transaction]  # операции окна истории (включая период), без отмеченных переводов
    period_txs: list[Transaction]  # операции периода без отмеченных переводов
    # Операции периода, отмеченные пользователем как переводы (Stage 3F): не
    # доходы и не расходы, но двигают остатки счетов.
    period_marked: list[Transaction]
    transfers: list[Transfer]  # переводы периода
    accounts: dict[int, Account]
    categories: dict[int, Category]
    first_tx_date: date | None


def build_insights(db: Session, *, period_key: InsightPeriodKey, today: date, today_utc: date, now: datetime) -> InsightsOut:
    period = resolve_period(period_key, today)
    window_start = min(period.start, period.end - timedelta(days=HISTORY_WINDOW_DAYS))
    txs = list(
        db.scalars(
            select(Transaction)
            .where(Transaction.occurred_at >= window_start, Transaction.occurred_at <= period.end)
            .order_by(Transaction.occurred_at, Transaction.id)
        )
    )
    first = db.scalar(select(func.min(Transaction.occurred_at)))
    # Единое правило (app/engine/flows.py): отмеченные переводы не входят ни в
    # доходы, ни в расходы, ни в обычный уровень трат.
    counted = [t for t in txs if not is_transfer(t)]
    data = _Data(
        period=period,
        today=today,
        now=now,
        txs=counted,
        period_txs=[t for t in counted if t.occurred_at >= period.start],
        period_marked=[t for t in txs if is_transfer(t) and t.occurred_at >= period.start],
        transfers=list(
            db.scalars(select(Transfer).where(Transfer.occurred_at >= period.start, Transfer.occurred_at <= period.end))
        ),
        accounts={a.id: a for a in db.scalars(select(Account))},
        categories={c.id: c for c in db.scalars(select(Category))},
        first_tx_date=_utc_date(first) if first is not None else None,
    )
    # Бюджеты, цели и особенности данных — из контекста Stage 2F (те же
    # расчёты, что у экранов «Бюджеты» и «Цели»).
    ctx = context_builder.build_context(db, months=3, horizon_days=30, today=today, today_utc=today_utc, now=now)

    insights: list[InsightOut] = []
    unavailable: list[UnavailableInsightOut] = []
    # Валюта с одними отмеченными переводами тоже показывается: доходы и
    # расходы — ноль, переводы — отдельной строкой.
    currencies = sorted({t.currency for t in [*data.period_txs, *data.period_marked]})
    if not data.period_txs and not data.period_marked:
        for kind in ("cash_flow", "spending_structure"):
            unavailable.append(
                UnavailableInsightOut(type=kind, kind="insufficient_data", reason="За выбранный период нет операций.")  # type: ignore[arg-type]
            )
    for cur in currencies:
        insights.append(_cash_flow(data, cur))
        spending = _spending_structure(data, cur)
        if spending is not None:
            insights.append(spending)
        else:
            unavailable.append(
                UnavailableInsightOut(type="spending_structure", currency=cur, kind="nothing_found", reason="За период нет расходов в этой валюте.")
            )
        _large_expenses(data, cur, insights, unavailable)
    _recurring_expenses(db, data, insights, unavailable)
    _budgets(ctx, today, insights, unavailable)
    _goals(ctx, today, insights, unavailable)
    _data_quality(ctx, data, insights, unavailable)

    insights.sort(key=lambda i: (SEVERITY_ORDER[i.severity], TYPE_ORDER.index(i.type), i.currency or ""))
    return InsightsOut(
        generated_at=now,
        today=today,
        period=period.out(),
        currencies=currencies,
        insights=insights,
        unavailable=unavailable,
        comparison=build_comparison(db, period_key=period_key, today=today),
    )


DEBT_UNCERTAINTY = (
    "Погашения долгов не входят в расходы на жизнь, чтобы покупки по кредитной карте, уже записанные расходами, "
    "не учитывались второй раз. Записаны ли эти покупки, приложение проверить не может: если нет, расходы на "
    "жизнь занижены на часть погашений."
)


def is_debt_repayment(categories: dict[int, Category], t: Transaction) -> bool:
    """Погашение долга по единому правилу (app/engine/flows.py): назначение
    «погашение», выбранное пользователем, операция платежа по долгу или
    категория «Погашение долга». Других догадок нет."""
    return flow_kind(t, debt_repayment_category_ids(categories.values())) == "debt_repayment"


def _is_debt_repayment(data: _Data, t: Transaction) -> bool:
    return is_debt_repayment(data.categories, t)


def living_expense_threshold(
    txs: list[Transaction], categories: dict[int, Category], cur: str
) -> tuple[list[Transaction], rules.LargeExpenseThreshold | None]:
    """Обычный уровень трат и порог крупного расхода по расходам на жизнь
    одной валюты (без подтверждённых погашений долгов). Общий для инсайта
    «Крупные расходы» и предупреждений Stage 3E."""
    baseline = [
        t
        for t in txs
        if t.currency == cur and t.type == "expense" and not is_transfer(t) and not is_debt_repayment(categories, t)
    ]
    return baseline, rules.large_expense_threshold([t.amount_minor for t in baseline])


def _coverage_limitation(data: _Data) -> list[str]:
    first = data.first_tx_date
    if first is not None and first > data.period.start.date():
        return [f"Операции в приложении есть только с {_d(first)}: начало периода не покрыто."]
    return []


# --- 1. доходы и расходы -------------------------------------------------------------------


def _cash_flow(data: _Data, cur: str) -> InsightOut:
    txs = [t for t in data.period_txs if t.currency == cur]
    income = money_sum((Money.of(t.amount_minor, cur) for t in txs if t.type == "income"), cur)
    expense = money_sum((Money.of(t.amount_minor, cur) for t in txs if t.type == "expense"), cur)
    net = income - expense
    debt_in = money_sum((Money.of(t.amount_minor, cur) for t in txs if t.debt_payment_id and t.type == "income"), cur)
    debt_out = money_sum((Money.of(t.amount_minor, cur) for t in txs if _is_debt_repayment(data, t)), cur)
    transfers = [tr for tr in data.transfers if tr.currency == cur]
    transfers_total = money_sum((Money.of(tr.amount_minor, cur) for tr in transfers), cur)

    # Изменение остатка активных счетов — из движений за период: операции
    # плюс переводы, затрагивающие активные счета (перевод между двумя
    # активными счетами в сумме даёт ноль).
    active = {aid for aid, a in data.accounts.items() if a.is_active and a.currency == cur}
    marked = [t for t in data.period_marked if t.currency == cur]
    change = Money.zero(cur)
    for t in [*txs, *marked]:  # отмеченные переводы тоже двигают остатки
        if t.account_id in active:
            amount = Money.of(t.amount_minor, cur)
            change = change + amount if t.type == "income" else change - amount
    for tr in transfers:
        amount = Money.of(tr.amount_minor, cur)
        if tr.to_account_id in active:
            change = change + amount
        if tr.from_account_id in active:
            change = change - amount

    metrics = [
        InsightMetricOut(label="Доходы", money=_out(income)),
        InsightMetricOut(label="Расходы", money=_out(expense)),
        InsightMetricOut(label="Чистый поток", money=_out(net)),
        InsightMetricOut(label="Изменение остатка на активных счетах", money=_out(change)),
    ]
    if debt_out.minor:
        metrics.insert(2, InsightMetricOut(label="Расходы на жизнь (без погашений долгов)", money=_out(expense - debt_out)))
    items: list[InsightItemOut] = []
    if transfers:
        items.append(
            InsightItemOut(
                label="Переводы между своими счетами",
                money=_out(transfers_total),
                note=f"{len(transfers)} шт.; не входят ни в доходы, ни в расходы",
            )
        )
    if marked:
        items.append(
            InsightItemOut(
                label="Отмечены вами как переводы",
                money=_out(money_sum((Money.of(t.amount_minor, cur) for t in marked), cur)),
                note=f"{len(marked)} шт.; не входят ни в доходы, ни в расходы",
            )
        )
    if debt_out.minor:
        items.append(
            InsightItemOut(
                label="В расходах: погашение долгов",
                money=_out(debt_out),
                note="входит в денежный поток, но не в расходы на жизнь; повторный ли это учёт покупок — проверить нельзя",
            )
        )
    if debt_in.minor:
        items.append(InsightItemOut(label="В доходах: возврат долгов", money=_out(debt_in), note="возврат ранее выданных денег, а не заработок"))

    if net.is_negative:
        summary = f"Расходы превысили доходы на {_fmt(-net)}: доходы {_fmt(income)}, расходы {_fmt(expense)}."
    elif net.is_positive:
        summary = f"Доходы превысили расходы на {_fmt(net)}: доходы {_fmt(income)}, расходы {_fmt(expense)}."
    else:
        summary = f"Доходы и расходы равны: по {_fmt(income)}."
    if change != net:
        summary += f" Остаток на активных счетах за период изменился на {_fmt(change)}."

    limitations = _coverage_limitation(data)
    if not data.period.complete:
        limitations.append("Месяц ещё идёт: итоги изменятся.")
    limitations.append("Возврат покупки в приложении записывается как доход: он увеличивает доходы, а не уменьшает расходы.")
    if debt_out.minor:
        limitations.append(DEBT_UNCERTAINTY)
    return InsightOut(
        id=f"cash_flow:{cur}",
        type="cash_flow",
        title="Доходы и расходы",
        severity="attention" if net.is_negative else "info",
        confidence="medium" if _coverage_limitation(data) else "high",
        period=data.period.out(),
        currency=cur,
        metrics=metrics,
        items=items,
        summary=summary,
        limitations=limitations,
        link=InsightLinkOut(to="/analytics", label="Аналитика"),
    )


# --- 2. структура расходов -----------------------------------------------------------------


def _spending_structure(data: _Data, cur: str) -> InsightOut | None:
    all_expenses = [t for t in data.period_txs if t.currency == cur and t.type == "expense"]
    # Структура — по расходам на жизнь: погашение долга не категория трат,
    # иначе покупки по кредитке и их погашение заняли бы две доли.
    expenses = [t for t in all_expenses if not _is_debt_repayment(data, t)]
    debt_total = money_sum((Money.of(t.amount_minor, cur) for t in all_expenses if _is_debt_repayment(data, t)), cur)
    if not expenses:
        return None
    total = money_sum((Money.of(t.amount_minor, cur) for t in expenses), cur)
    by_cat: dict[int, Money] = defaultdict(lambda: Money.zero(cur))
    for t in expenses:
        by_cat[t.category_id] = by_cat[t.category_id] + Money.of(t.amount_minor, cur)
    ranked = sorted(by_cat.items(), key=lambda kv: (-kv[1].minor, kv[0]))
    items = [
        InsightItemOut(
            label=_label(data.categories[cid].name if cid in data.categories else None),
            money=_out(amount),
            percent=round_percent(share_percent(amount, total)) or 0.0,
        )
        for cid, amount in ranked[:TOP_CATEGORIES]
    ]
    rest = ranked[TOP_CATEGORIES:]
    if rest:
        rest_total = money_sum((m for _, m in rest), cur)
        items.append(
            InsightItemOut(
                label=f"Остальные категории ({len(rest)})",
                money=_out(rest_total),
                percent=round_percent(share_percent(rest_total, total)) or 0.0,
            )
        )
    top = items[0]
    summary = f"Больше всего ушло на «{top.label}»: {_fmt(Money.of(top.money.minor, cur))} — {_pct(top.percent)} всех расходов."  # type: ignore[union-attr]
    if len(ranked) > 1:
        first3 = ranked[:3]
        share3 = round_percent(share_percent(money_sum((m for _, m in first3), cur), total)) or 0.0
        summary += f" На {len(first3)} крупнейшие категории приходится {_pct(share3)}."
    limitations = _coverage_limitation(data)
    if len(expenses) < 5:
        limitations.append(f"Всего {len(expenses)} расходных операций — структура может быть случайной.")
    limitations.append("Доли округлены до 0,1%, поэтому их сумма может немного отличаться от 100%.")
    if debt_total.minor:
        limitations.append(f"Погашения долгов на {_fmt(debt_total)} в структуру не входят. {DEBT_UNCERTAINTY}")
    return InsightOut(
        id=f"spending_structure:{cur}",
        type="spending_structure",
        title="Структура расходов",
        severity="info",
        confidence="low" if len(expenses) < 5 else ("medium" if _coverage_limitation(data) else "high"),
        period=data.period.out(),
        currency=cur,
        metrics=[
            InsightMetricOut(label="Расходы на жизнь", money=_out(total)),
            InsightMetricOut(label="Расходных операций", count=len(expenses)),
            InsightMetricOut(label="Категорий", count=len(ranked)),
        ],
        items=items,
        summary=summary,
        limitations=limitations,
        link=InsightLinkOut(to="/analytics", label="Аналитика"),
    )


# --- 3. крупные расходы ----------------------------------------------------------------------


def _large_expenses(data: _Data, cur: str, insights: list[InsightOut], unavailable: list[UnavailableInsightOut]) -> None:
    baseline, threshold = living_expense_threshold(data.txs, data.categories, cur)
    if threshold is None:
        unavailable.append(
            UnavailableInsightOut(
                type="large_expenses",
                currency=cur,
                kind="insufficient_data",
                reason=(
                    f"Чтобы понять обычный уровень трат, нужно хотя бы {rules.LARGE_EXPENSE_MIN_BASELINE} расходов "
                    f"за полгода, сейчас {len(baseline)}."
                ),
            )
        )
        return
    period_expenses = [
        t for t in data.period_txs if t.currency == cur and t.type == "expense" and not _is_debt_repayment(data, t)
    ]
    large = sorted(
        (t for t in period_expenses if t.amount_minor >= threshold.threshold_minor),
        key=lambda t: (-t.amount_minor, t.occurred_at),
    )
    if not large:
        unavailable.append(
            UnavailableInsightOut(
                type="large_expenses",
                currency=cur,
                kind="nothing_found",
                reason=f"Расходов заметно выше обычного уровня (от {_fmt(Money.of(threshold.threshold_minor, cur))}) за период нет.",
            )
        )
        return
    period_total = money_sum((Money.of(t.amount_minor, cur) for t in period_expenses), cur)
    large_total = money_sum((Money.of(t.amount_minor, cur) for t in large), cur)
    median = Money.of(threshold.median_minor, cur)
    items = []
    for t in large[:TOP_LARGE_EXPENSES]:
        amount = Money.of(t.amount_minor, cur)
        category = _label(data.categories[t.category_id].name if t.category_id in data.categories else None)
        account = _label(data.accounts[t.account_id].name if t.account_id in data.accounts else None)
        times = rules.times_median(t.amount_minor, threshold.median_minor)
        items.append(
            InsightItemOut(
                label=f"{category} · {account}",
                money=_out(amount),
                percent=round_percent(share_percent(amount, period_total)) or 0.0,
                date=_utc_date(t.occurred_at),
                note=f"в {str(times).replace('.', ',')} раза больше обычной траты",
            )
        )
    share = round_percent(share_percent(large_total, period_total)) or 0.0
    summary = (
        f"{len(large)} {_plural(len(large), 'расход', 'расхода', 'расходов')} заметно выше обычного уровня: вместе "
        f"{_fmt(large_total)}, это {_pct(share)} расходов на жизнь за период. Обычная трата — около {_fmt(median)}. "
        "Крупный расход не обязательно ошибка или лишняя трата — проверьте, был ли он запланирован."
    )
    insights.append(
        InsightOut(
            id=f"large_expenses:{cur}",
            type="large_expenses",
            title="Крупные расходы",
            severity="attention",
            confidence="high" if threshold.baseline_count >= 50 else "medium",
            period=data.period.out(),
            currency=cur,
            metrics=[
                InsightMetricOut(label="Крупных расходов", count=len(large)),
                InsightMetricOut(label="Их сумма", money=_out(large_total)),
                InsightMetricOut(label="Доля в расходах на жизнь", percent=share),
                InsightMetricOut(label="Обычная трата (медиана расходов на жизнь за полгода)", money=_out(median)),
            ],
            items=items,
            summary=summary,
            limitations=[
                f"Обычный уровень посчитан по {threshold.baseline_count} расходам на жизнь за полгода (без погашений долгов); порог — "
                f"{_fmt(Money.of(threshold.threshold_minor, cur))}."
            ],
            link=InsightLinkOut(to="/transactions", label="Операции"),
        )
    )


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


# --- 4. повторяющиеся расходы --------------------------------------------------------------


def _recurring_expenses(db: Session, data: _Data, insights: list[InsightOut], unavailable: list[UnavailableInsightOut]) -> None:
    first = data.first_tx_date
    history_days = (data.period.end.date() - first).days if first else 0
    if first is None or history_days < RECURRING_MIN_HISTORY_DAYS:
        since = f" (сейчас операции есть с {_d(first)})" if first else ""
        unavailable.append(
            UnavailableInsightOut(
                type="recurring_expenses",
                kind="insufficient_data",
                reason=f"Чтобы подтвердить регулярность платежей, нужна история хотя бы за 2 месяца{since}.",
            )
        )
        return
    groups: dict[tuple[str, int, int, int], list[Transaction]] = defaultdict(list)
    for t in data.txs:
        if t.type == "expense" and not _is_debt_repayment(data, t):
            groups[(t.currency, t.category_id, t.account_id, t.amount_minor)].append(t)
    rules_keys = {
        (r.currency, r.category_id, r.account_id, r.amount_minor)
        for r in db.scalars(select(RecurringTransaction).where(RecurringTransaction.is_active.is_(True), RecurringTransaction.type == "expense"))
    }
    period_start = data.period.start.date()
    found: list[tuple[tuple[str, int, int, int], rules.Cadence, list[date]]] = []
    for key, items in groups.items():
        days = [_utc_date(t.occurred_at) for t in items]
        cadence = rules.detect_cadence(days)
        # Платёж должен быть актуален для периода: последнее списание не
        # раньше, чем за один интервал до начала периода.
        if cadence is None or max(days) < period_start - timedelta(days=35 if cadence == "monthly" else 8):
            continue
        found.append((key, cadence, sorted(days)))
    if not found:
        unavailable.append(
            UnavailableInsightOut(
                type="recurring_expenses",
                kind="nothing_found",
                reason="Одинаковых списаний с устойчивым интервалом (месяц или неделя) не найдено.",
            )
        )
        return
    by_currency: dict[str, list] = defaultdict(list)
    for entry in found:
        by_currency[entry[0][0]].append(entry)
    for cur, entries in sorted(by_currency.items()):
        entries.sort(key=lambda e: (-e[0][3], e[2][-1]))
        monthly_total = money_sum((Money.of(k[3], cur) for k, cad, _ in entries if cad == "monthly"), cur)
        items = []
        for (c, cat_id, acc_id, amount), cadence, days in entries[:MAX_RECURRING_ITEMS]:
            category = _label(data.categories[cat_id].name if cat_id in data.categories else None)
            account = _label(data.accounts[acc_id].name if acc_id in data.accounts else None)
            known = (c, cat_id, acc_id, amount) in rules_keys
            items.append(
                InsightItemOut(
                    label=f"{category} · {account}",
                    money=_out(Money.of(amount, cur)),
                    date=days[-1],
                    note=f"{'ежемесячно' if cadence == 'monthly' else 'еженедельно'}, {len(days)} раз подряд"
                    + ("; уже есть в регулярных операциях" if known else "; в регулярных операциях не заведён"),
                )
            )
        min_occ = min(len(d) for _, _, d in entries)
        summary = (
            f"Найдено {len(entries)} {_plural(len(entries), 'повторяющееся списание', 'повторяющихся списания', 'повторяющихся списаний')}"
            " с одинаковой суммой и устойчивым интервалом — возможно, подписки или регулярные платежи."
        )
        if monthly_total.minor:
            summary += f" Ежемесячные из них — {_fmt(monthly_total)} в месяц."
        insights.append(
            InsightOut(
                id=f"recurring_expenses:{cur}",
                type="recurring_expenses",
                title="Возможные регулярные платежи",
                severity="info",
                confidence="high" if min_occ >= 4 else "medium",
                period=data.period.out(),
                currency=cur,
                metrics=[
                    InsightMetricOut(label="Найдено", count=len(entries)),
                    InsightMetricOut(label="Ежемесячные платежи в сумме", money=_out(monthly_total)),
                ],
                items=items,
                summary=summary,
                limitations=[
                    "Регулярность определена по совпадению категории, счёта и суммы и по интервалам между списаниями; "
                    "платежи с меняющейся суммой не распознаются.",
                    "Это наблюдение по истории, а не гарантия будущих списаний.",
                ],
                link=InsightLinkOut(to="/recurring", label="Регулярные операции"),
            )
        )


# --- 5. бюджеты -----------------------------------------------------------------------------


def _budgets(ctx, today: date, insights: list[InsightOut], unavailable: list[UnavailableInsightOut]) -> None:
    budgets = ctx.budgets
    if not budgets.items:
        unavailable.append(
            UnavailableInsightOut(type="budgets", kind="not_applicable", reason="На текущий месяц бюджетов нет.")
        )
        return
    start, end = month_bounds(today.year, today.month)
    period = InsightPeriodOut(
        key="current_month", date_from=start.date(), date_to=end.date(),
        label=f"{MONTHS_RU[today.month - 1]} {today.year} (месяц ещё идёт)", complete=False,
    )
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    for summary_row in budgets.summary_by_currency:
        cur = summary_row.currency
        rows = []
        for b in (x for x in budgets.items if x.amount.currency == cur):
            projected = rules.projected_month_spend(b.spent.minor, today.day, days_in_month)
            at_risk = b.status != "exceeded" and projected is not None and projected > b.amount.minor
            rows.append((b, projected, at_risk))
        exceeded = [r for r in rows if r[0].status == "exceeded"]
        at_risk = [r for r in rows if r[2]]
        rows.sort(key=lambda r: (r[0].status != "exceeded", not r[2], -r[0].usage_percent))
        items = []
        for b, projected, risk in rows[:MAX_BUDGET_ITEMS]:
            if b.status == "exceeded":
                note = f"лимит {_fmt(Money.of(b.amount.minor, cur))} превышен на {_fmt(Money.of(b.spent.minor - b.amount.minor, cur))}"
            else:
                note = f"лимит {_fmt(Money.of(b.amount.minor, cur))}, осталось {_fmt(Money.of(b.remaining.minor, cur))}"
                if risk:
                    note += f"; если тратить так же, за месяц выйдет около {_fmt(Money.of(projected, cur))}"  # type: ignore[arg-type]
            items.append(InsightItemOut(label=_label(b.label), money=b.spent, percent=b.usage_percent, note=note))
        if exceeded:
            summary = f"Превышено бюджетов: {len(exceeded)} из {len(rows)}."
        elif at_risk:
            summary = f"Бюджеты пока в пределах лимитов, но при текущем темпе трат могут быть превышены: {len(at_risk)} из {len(rows)}."
        else:
            summary = f"Все {len(rows)} бюджетов в пределах лимитов."
        if summary_row.usage_percent is not None:
            summary += f" Использовано {_pct(summary_row.usage_percent)} общего лимита."
        limitations = []
        if today.day < rules.BUDGET_PACE_MIN_DAYS:
            limitations.append("Прошло меньше недели месяца — риск превышения по темпу трат не оценивается.")
        else:
            limitations.append("Риск превышения — оценка по темпу трат с начала месяца, а не прогноз.")
        insights.append(
            InsightOut(
                id=f"budgets:{cur}",
                type="budgets",
                title="Бюджеты месяца",
                severity="warning" if exceeded else ("attention" if at_risk or summary_row.warning else "info"),
                confidence="high" if not at_risk else "medium",
                period=period,
                currency=cur,
                metrics=[
                    InsightMetricOut(label="Общий лимит", money=summary_row.limit),
                    InsightMetricOut(label="Потрачено", money=summary_row.spent),
                    InsightMetricOut(label="Использовано", percent=summary_row.usage_percent),
                    InsightMetricOut(label="Превышено", count=len(exceeded)),
                ],
                items=items,
                summary=summary,
                limitations=limitations,
                link=InsightLinkOut(to="/budgets", label="Бюджеты"),
            )
        )


# --- 6. цели ------------------------------------------------------------------------------------


def _goals(ctx, today: date, insights: list[InsightOut], unavailable: list[UnavailableInsightOut]) -> None:
    goals = [g for g in ctx.goals.items if g.status != "archived"]
    if not goals:
        unavailable.append(UnavailableInsightOut(type="goals", kind="not_applicable", reason="Активных целей нет."))
        return
    items = []
    overdue = 0
    for g in goals[:MAX_GOAL_ITEMS]:
        target, saved, remaining = (Money.of(x.minor, x.currency) for x in (g.target, g.saved, g.remaining))
        if g.status == "completed":
            note = f"цель достигнута: накоплено {_fmt(saved)} из {_fmt(target)}"
        elif g.required_monthly is not None and g.target_date is not None:
            note = (
                f"осталось {_fmt(remaining)}; чтобы успеть к {_d(g.target_date)}, нужно "
                f"{_fmt(Money.of(g.required_monthly.minor, g.required_monthly.currency))} в месяц ({g.months_left} мес.)"
            )
        elif g.plan_null_reason == "target_date_passed":
            overdue += 1
            note = f"осталось {_fmt(remaining)}; срок {_d(g.target_date)} уже прошёл"  # type: ignore[arg-type]
        else:
            note = f"осталось {_fmt(remaining)}; срок не задан — план по сроку или взносу можно посчитать в помощнике"
        items.append(InsightItemOut(label=_label(g.label), money=_out(saved), percent=g.progress_percent, date=g.target_date, note=note))
    completed = sum(1 for g in goals if g.status == "completed")
    currencies = sorted({g.target.currency for g in goals})
    summary = f"Целей: {len(goals)}, достигнуто: {completed}."
    if overdue:
        summary += f" У {overdue} срок прошёл, а цель не достигнута — стоит обновить срок или план."
    no_date = sum(1 for g in goals if g.status == "active" and g.plan_null_reason == "no_target_date")
    if no_date:
        summary += f" Без срока: {no_date} — для них ежемесячный взнос зависит от выбранного срока."
    insights.append(
        InsightOut(
            id="goals:all",
            type="goals",
            title="Финансовые цели",
            severity="attention" if overdue else "info",
            confidence="high",
            period=InsightPeriodOut(key="today", date_from=today, date_to=today, label=f"на {_d(today)}", complete=True),
            currency=currencies[0] if len(currencies) == 1 else None,
            metrics=[
                InsightMetricOut(label="Активных целей", count=len(goals) - completed),
                InsightMetricOut(label="Достигнуто", count=completed),
            ],
            items=items,
            summary=summary,
            limitations=["Накопления по цели — взносы, записанные в цели; остатки на счетах в них не входят."],
            link=InsightLinkOut(to="/goals", label="Цели"),
        )
    )


# --- 7. качество данных -----------------------------------------------------------------------


_CONTEXT_QUALITY_SKIP = {"label_sanitized", "list_truncated"}


def _data_quality(ctx, data: _Data, insights: list[InsightOut], unavailable: list[UnavailableInsightOut]) -> None:
    issues: list[InsightItemOut] = []
    coverage = _coverage_limitation(data)
    if coverage:
        issues.append(InsightItemOut(label="История короче периода", date=data.first_tx_date, note=coverage[0]))
    for kind, name in OTHER_CATEGORY_NAMES.items():
        other_ids = {cid for cid, c in data.categories.items() if c.is_default and c.name == name}
        for cur in sorted({t.currency for t in data.period_txs}):
            txs = [t for t in data.period_txs if t.currency == cur and t.type == kind]
            total = money_sum((Money.of(t.amount_minor, cur) for t in txs), cur)
            other = money_sum((Money.of(t.amount_minor, cur) for t in txs if t.category_id in other_ids), cur)
            if total.minor and other.minor:
                share = round_percent(share_percent(other, total)) or 0.0
                if share >= OTHER_CATEGORY_SHARE_WARNING:
                    what = "расходов" if kind == "expense" else "доходов"
                    issues.append(
                        InsightItemOut(
                            label=f"Много операций в «{name}»",
                            money=_out(other),
                            percent=share,
                            note=f"{_pct(share)} {what} периода без точной категории — выводы о структуре {what} менее надёжны",
                        )
                    )
    future = sum(1 for t in data.period_txs if t.occurred_at > data.now)
    if future:
        issues.append(InsightItemOut(label="Операции с будущей датой", note=f"{future} шт. уже учтены в итогах периода"))
    for q in ctx.data_quality:
        if q.code in _CONTEXT_QUALITY_SKIP:
            continue
        issues.append(InsightItemOut(label=QUALITY_TEXT[q.code].capitalize(), money=q.amount, note=f"{q.count} шт." if q.count else None))
    if not issues:
        unavailable.append(
            UnavailableInsightOut(type="data_quality", kind="nothing_found", reason="Проблем с полнотой и категориями данных не найдено.")
        )
        return
    insights.append(
        InsightOut(
            id="data_quality:all",
            type="data_quality",
            title="Надёжность выводов",
            severity="attention",
            confidence="high",
            period=data.period.out(),
            currency=None,
            metrics=[InsightMetricOut(label="Замечаний", count=len(issues))],
            items=issues,
            summary="Некоторые данные неполные или неоднозначные — часть выводов выше может быть неточной.",
            limitations=[],
            link=InsightLinkOut(to="/transactions", label="Операции"),
        )
    )
