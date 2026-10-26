"""Финансовые предупреждения (Stage 3E).

Актуальные предупреждения по текущим данным — только чтение, без записи в
БД и без модели. Каждое условие и каждое число — из уже существующих
расчётов, а не новой логики:
  * бюджеты — финансовый контекст Stage 2F (тот же расчёт, что у экрана
    «Бюджеты»), темп трат — engine.insights.projected_month_spend (Stage 3C);
  * крупный расход — порог Stage 3C по расходам на жизнь
    (builder.living_expense_threshold), погашения долгов не входят ни в
    обычный уровень, ни в кандидаты;
  * рост категории — сравнение периодов Stage 3D (текущий месяц против тех
    же дней прошлого), только при надёжной базе;
  * просроченная цель — цели из контекста (модель целей Stage 2C).

Повторы. У каждого предупреждения стабильный key: тип + сущность + период
(«budget_exceeded:<бюджет>:<месяц>», «large_expense:<операция>»,
«category_spike:<валюта>:<категория>:<начало месяца>», «goal_overdue:<цель>:
<срок>»). Одно событие даёт один ключ при любом числе запросов; в ответе
ключи уникальны, а превышение бюджета и риск по темпу для одного бюджета
взаимоисключающие. Интерфейс скрывает предупреждения по этому ключу.

Существующие уведомления (app/notifications) — отдельный журнал событий с
историей прочтения; эти предупреждения его не пишут и не дублируют в нём.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.context import builder as context_builder
from app.context.labels import sanitize_label
from app.db.models import Account, Category, Transaction
from app.engine import insights as rules
from app.engine.money import Money
from app.insights.builder import MONTHS_RU, living_expense_threshold
from app.insights.comparison import OTHER_EXPENSE_CATEGORY, OTHER_SHARE_WARNING, build_comparison
from app.schemas.insights import (
    FinancialWarningOut,
    InsightLinkOut,
    LargeExpenseGroupOut,
    InsightMetricOut,
    WarningPeriodOut,
    WarningsOut,
)
from app.schemas.money import MoneyOut

HISTORY_DAYS = 183  # обычный уровень трат — как у Stage 3C
LARGE_EXPENSE_RECENT_DAYS = 30  # крупные расходы — за последние 30 дней
MAX_LARGE_EXPENSE_WARNINGS = 5
# Темп трат по бюджету оценивается только при достаточных данных месяца.
BUDGET_PACE_MIN_OPERATIONS = 3
# Рост категории — только существенный и на заметной базе, иначе процент
# статистически неинформативен (100 ₽ → 400 ₽ = «+300%»).
CATEGORY_SPIKE_MIN_DAYS = 7
CATEGORY_SPIKE_MIN_PERCENT = 50
CATEGORY_SPIKE_MIN_DELTA_SHARE = 10  # прирост ≥ 10% всех расходов на жизнь прошлого периода
CATEGORY_SPIKE_MIN_BASE_SHARE = 3  # база ≥ 3% всех расходов на жизнь прошлого периода
TYPE_ORDER = ["budget_exceeded", "goal_overdue", "budget_pace_risk", "category_spike", "large_expense"]


def _out(m: Money) -> MoneyOut:
    return MoneyOut(minor=m.minor, currency=m.currency.code)


def _m(out: MoneyOut) -> Money:
    return Money.of(out.minor, out.currency)


def _d(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _pct(value: float) -> str:
    return f"{value:.1f}".replace(".", ",") + "%"


def _label(raw: str | None) -> str:
    return sanitize_label(raw)[0] or "—"


def build_warnings(db: Session, *, today: date, today_utc: date, now: datetime) -> WarningsOut:
    ctx = context_builder.build_context(db, months=3, horizon_days=30, today=today, today_utc=today_utc, now=now)
    categories = {c.id: c for c in db.scalars(select(Category))}
    warnings: list[FinancialWarningOut] = []
    limitations: list[str] = []

    _budget_warnings(db, ctx, today, warnings, limitations)
    groups: list[LargeExpenseGroupOut] = []
    _large_expense_warnings(db, categories, now, warnings, limitations, groups)
    _category_spike_warnings(db, categories, today, warnings, limitations)
    _goal_warnings(ctx, today, warnings, limitations)

    unique: dict[str, FinancialWarningOut] = {}
    for w in warnings:
        unique.setdefault(w.key, w)
    # Внутри типа — порядок сборки (крупные расходы — по убыванию суммы).
    position = {key: i for i, key in enumerate(unique)}
    ordered = sorted(
        unique.values(), key=lambda w: (w.severity != "warning", TYPE_ORDER.index(w.type), position[w.key])
    )
    return WarningsOut(
        generated_at=now, today=today, warnings=ordered, limitations=limitations, large_expense_groups=groups
    )


# --- A. бюджеты ----------------------------------------------------------------------------


def _budget_warnings(db, ctx, today: date, warnings: list, limitations: list) -> None:
    budgets = ctx.budgets.items
    if not budgets:
        return  # бюджет не установлен — предупреждать не о чем
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    start = datetime(today.year, today.month, 1, tzinfo=timezone.utc)
    period = WarningPeriodOut(
        date_from=start.date(),
        date_to=date(today.year, today.month, days_in_month),
        label=f"{MONTHS_RU[today.month - 1]} {today.year}",
    )
    month_ops: dict[tuple[int, str], int] = {}
    for t in db.scalars(
        select(Transaction).where(Transaction.type == "expense", Transaction.occurred_at >= start)
    ):
        if t.occurred_at.astimezone(timezone.utc).month == today.month:
            month_ops[(t.category_id, t.currency)] = month_ops.get((t.category_id, t.currency), 0) + 1
    pace_skipped = 0
    for b in budgets:
        cur = b.amount.currency
        limit, spent = _m(b.amount), _m(b.spent)
        label = _label(b.label)
        metrics = [
            InsightMetricOut(label="Потрачено", money=b.spent),
            InsightMetricOut(label="Лимит", money=b.amount),
            InsightMetricOut(label="Использовано", percent=b.usage_percent),
        ]
        link = InsightLinkOut(to="/budgets", label="Бюджеты")
        if b.status == "exceeded":
            over = spent - limit
            warnings.append(
                FinancialWarningOut(
                    key=f"budget_exceeded:{b.id}:{today.year:04d}-{today.month:02d}",
                    type="budget_exceeded",
                    kind="fact",
                    severity="warning",
                    title=f"Бюджет «{label}» превышен",
                    message=f"Потрачено {spent.format()} при лимите {limit.format()} — больше на {over.format()}.",
                    currency=cur,
                    metrics=[*metrics, InsightMetricOut(label="Превышение", money=_out(over))],
                    period=period,
                    recommendation="Посмотрите операции этой категории за месяц. Если лимит был занижен — пересмотрите бюджет.",
                    link=link,
                )
            )
            continue
        projected = rules.projected_month_spend(spent.minor, today.day, days_in_month)
        if projected is None:
            continue  # первая неделя месяца — темп ничего не говорит
        if month_ops.get((b.category_id, cur), 0) < BUDGET_PACE_MIN_OPERATIONS:
            pace_skipped += 1
            continue
        if projected <= limit.minor:
            continue
        days_left = days_in_month - today.day
        warnings.append(
            FinancialWarningOut(
                key=f"budget_pace_risk:{b.id}:{today.year:04d}-{today.month:02d}",
                type="budget_pace_risk",
                kind="estimate",
                severity="attention",
                title=f"Бюджет «{label}» может быть превышен",
                message=(
                    f"Сейчас потрачено {spent.format()} из {limit.format()}. Если тратить так же, как с начала месяца, "
                    f"к концу месяца выйдет около {Money.of(projected, cur).format()}. Это оценка по темпу, а не факт."
                ),
                currency=cur,
                metrics=[*metrics, InsightMetricOut(label="Оценка за месяц", money=_out(Money.of(projected, cur)))],
                period=period,
                recommendation=(
                    f"Чтобы уложиться в лимит, до конца месяца ({days_left} дн.) в этой категории можно потратить ещё "
                    f"{_m(b.remaining).format()}."
                ),
                link=link,
            )
        )
    if today.day < rules.BUDGET_PACE_MIN_DAYS:
        limitations.append(
            f"Риск превышения бюджетов по темпу трат оценивается с {rules.BUDGET_PACE_MIN_DAYS}-го числа: "
            "в начале месяца данных слишком мало."
        )
    elif pace_skipped:
        limitations.append(
            f"Для {pace_skipped} бюджетов темп трат не оценивался: в их категориях меньше "
            f"{BUDGET_PACE_MIN_OPERATIONS} операций за месяц."
        )


# --- B. крупные расходы ----------------------------------------------------------------------


def _large_expense_warnings(db, categories, now: datetime, warnings: list, limitations: list, groups: list) -> None:
    history_start = now - timedelta(days=HISTORY_DAYS)
    txs = list(
        db.scalars(
            select(Transaction)
            .where(Transaction.occurred_at >= history_start, Transaction.occurred_at <= now)
            .order_by(Transaction.occurred_at, Transaction.id)
        )
    )
    accounts = {a.id: a for a in db.scalars(select(Account))}
    recent_from = (now - timedelta(days=LARGE_EXPENSE_RECENT_DAYS - 1)).date()
    for cur in sorted({t.currency for t in txs if t.type == "expense"}):
        baseline, threshold = living_expense_threshold(txs, categories, cur)
        if threshold is None:
            limitations.append(
                f"Крупные расходы в {cur} не проверялись: для оценки обычного уровня трат нужно хотя бы "
                f"{rules.LARGE_EXPENSE_MIN_BASELINE} расходов за полгода, сейчас {len(baseline)}."
            )
            continue
        large = sorted(
            (
                t
                for t in baseline
                if t.occurred_at.astimezone(timezone.utc).date() >= recent_from
                and t.amount_minor >= threshold.threshold_minor
            ),
            key=lambda t: (-t.amount_minor, -t.id),
        )
        median = Money.of(threshold.median_minor, cur)
        listed = large[:MAX_LARGE_EXPENSE_WARNINGS]
        if listed:
            # Сводка для интерфейса: те же операции, что и в предупреждениях
            # ниже, сумма — в одной валюте. Правила отбора не меняются.
            groups.append(
                LargeExpenseGroupOut(
                    currency=cur,
                    count=len(listed),
                    total=_out(Money.of(sum(t.amount_minor for t in listed), cur)),
                    keys=[f"large_expense:{t.id}" for t in listed],
                    period=WarningPeriodOut(
                        date_from=recent_from,
                        date_to=now.date(),
                        label=f"последние {LARGE_EXPENSE_RECENT_DAYS} дней",
                    ),
                )
            )
        for t in listed:
            amount = Money.of(t.amount_minor, cur)
            day = t.occurred_at.astimezone(timezone.utc).date()
            category = _label(categories[t.category_id].name if t.category_id in categories else None)
            account = _label(accounts[t.account_id].name if t.account_id in accounts else None)
            times = str(rules.times_median(t.amount_minor, threshold.median_minor)).replace(".", ",")
            warnings.append(
                FinancialWarningOut(
                    key=f"large_expense:{t.id}",
                    type="large_expense",
                    kind="observation",
                    severity="attention",
                    title=f"Крупный расход: {amount.format()}",
                    message=(
                        f"«{category}», счёт «{account}», {_d(day)}. Это в {times} раза больше вашей обычной траты "
                        f"({median.format()}). Крупный расход не означает ошибку или лишнюю трату."
                    ),
                    currency=cur,
                    # Сумма — в заголовке, обычная трата — в тексте: отдельные
                    # показатели только удлинили бы карточку.
                    metrics=[],
                    period=WarningPeriodOut(date_from=day, date_to=day, label=_d(day)),
                    recommendation=(
                        "Если это перевод на свой счёт или погашение долга — оформите его переводом или платежом "
                        "по долгу, и он не будет считаться расходом на жизнь."
                    ),
                    link=InsightLinkOut(to="/transactions", label="Операции"),
                )
            )
        if len(large) > MAX_LARGE_EXPENSE_WARNINGS:
            limitations.append(
                f"Показаны {MAX_LARGE_EXPENSE_WARNINGS} крупнейших расходов в {cur} из {len(large)} за 30 дней — "
                "остальные в инсайте «Крупные расходы»."
            )


# --- C. рост расходов по категории -----------------------------------------------------------


def _category_spike_warnings(db, categories, today: date, warnings: list, limitations: list) -> None:
    comparison = build_comparison(db, period_key="current_month", today=today)
    if comparison.unavailable_reason or not comparison.by_currency:
        return
    if comparison.current.days < CATEGORY_SPIKE_MIN_DAYS:
        limitations.append(
            f"Рост расходов по категориям проверяется с {CATEGORY_SPIKE_MIN_DAYS}-го числа: за несколько дней "
            "сравнение случайно."
        )
        return
    other_ids = {cid for cid, c in categories.items() if c.is_default and c.type == "expense" and c.name == OTHER_EXPENSE_CATEGORY}
    period = WarningPeriodOut(
        date_from=comparison.current.date_from,
        date_to=comparison.current.date_to,
        label=f"{comparison.current.label} против {comparison.previous.label}",
    )
    for item in comparison.by_currency:
        cur = item.currency
        if item.expense_without_debt_repayments.percent_null_reason == "insufficient_history":
            limitations.append(
                f"Рост расходов по категориям в {cur} не проверялся: за {comparison.previous.label} в приложении "
                "нет полных данных."
            )
            continue
        shares = [s for s in (item.other_share.current, item.other_share.previous) if s is not None]
        if any(s >= OTHER_SHARE_WARNING for s in shares):
            limitations.append(
                f"Рост расходов по категориям в {cur} не проверялся: доля «{OTHER_EXPENSE_CATEGORY}» "
                f"{_pct(max(shares))} — изменения по категориям недостоверны."
            )
            continue
        prev_total = item.expense_without_debt_repayments.previous.minor
        if prev_total <= 0:
            continue
        for row in item.categories:
            if row.category_id in other_ids or row.percent is None or row.previous.minor <= 0:
                continue  # нулевая база и «Прочее» — не основание для вывода о росте
            if row.percent < CATEGORY_SPIKE_MIN_PERCENT:
                continue
            if row.delta.minor * 100 < prev_total * CATEGORY_SPIKE_MIN_DELTA_SHARE:
                continue
            if row.previous.minor * 100 < prev_total * CATEGORY_SPIKE_MIN_BASE_SHARE:
                continue
            label = _label(row.label)
            warnings.append(
                FinancialWarningOut(
                    key=f"category_spike:{cur}:{row.category_id}:{comparison.current.date_from.isoformat()}",
                    type="category_spike",
                    kind="observation",
                    severity="attention",
                    title=f"Расходы на «{label}» заметно выросли",
                    message=(
                        f"{_m(row.current).format()} за {comparison.current.label} против {_m(row.previous).format()} "
                        f"за {comparison.previous.label}: на {_m(row.delta).format()} больше ({'+' + _pct(row.percent)})."
                    ),
                    currency=cur,
                    metrics=[
                        InsightMetricOut(label="Сейчас", money=row.current),
                        InsightMetricOut(label="Было", money=row.previous),
                        InsightMetricOut(label="Рост", percent=row.percent),
                    ],
                    period=period,
                    recommendation="Посмотрите операции этой категории: рост может быть разовым.",
                    link=InsightLinkOut(to="/analytics", label="Аналитика"),
                )
            )


# --- D. просроченные цели ---------------------------------------------------------------------


def _goal_warnings(ctx, today: date, warnings: list, limitations: list) -> None:
    no_date = 0
    for g in ctx.goals.items:
        if g.status != "active":
            continue  # выполненные и архивные цели не просрочены
        if g.target_date is None:
            no_date += 1
            continue
        if g.target_date >= today:
            continue
        label = _label(g.label)
        days = (today - g.target_date).days
        warnings.append(
            FinancialWarningOut(
                key=f"goal_overdue:{g.id}:{g.target_date.isoformat()}",
                type="goal_overdue",
                kind="fact",
                severity="attention",
                title=f"Срок цели «{label}» прошёл",
                message=(
                    f"Срок был {_d(g.target_date)} ({days} дн. назад). Накоплено {_m(g.saved).format()} из "
                    f"{_m(g.target).format()} ({_pct(g.progress_percent)}), осталось {_m(g.remaining).format()}."
                ),
                currency=g.target.currency,
                metrics=[
                    InsightMetricOut(label="Накоплено", money=g.saved),
                    InsightMetricOut(label="Осталось", money=g.remaining),
                    InsightMetricOut(label="Выполнено", percent=g.progress_percent),
                ],
                period=WarningPeriodOut(date_from=g.target_date, date_to=g.target_date, label=f"срок {_d(g.target_date)}"),
                recommendation="Перенесите срок цели или посчитайте новый план взносов в помощнике.",
                link=InsightLinkOut(to="/goals", label="Цели"),
            )
        )
    if no_date:
        limitations.append(f"Активных целей без срока: {no_date} — просрочку для них проверить нельзя.")
