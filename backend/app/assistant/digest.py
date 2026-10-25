"""Компактная сводка финансов для промпта локальной модели (Stage 3A).

Вход — только read-only контекст Stage 2F (FinancialContextOut). Модуль не
обращается к БД и не делает новых финансовых расчётов: он выбирает самое
важное, ограничивает длину списков и добавляет к каждой сумме готовую строку
(Money.format), чтобы модели не приходилось переводить minor-единицы.

Правила:
  * суммы разных валют не складываются — каждая сумма остаётся в своей валюте;
  * свободного текста нет (контекст его уже не содержит);
  * пользовательские названия в тексте сводки выводятся как строковые
    литералы JSON ("..."), то есть как данные, а не как инструкции.
"""

from __future__ import annotations

import json
import math

from app.engine.money import Money
from app.schemas.assistant import (
    AssistantDigest,
    DigestAccount,
    DigestBudget,
    DigestCategory,
    DigestDebt,
    DigestForecastItem,
    DigestForecastTotal,
    DigestGoal,
    DigestIndicators,
    DigestMeta,
    DigestMoney,
    DigestMonthFlow,
    DigestQualityNote,
)
from app.schemas.context import FinancialContextOut
from app.schemas.money import MoneyOut

MAX_ACCOUNTS = 10
MAX_BUDGETS = 10
MAX_DEBTS = 10
MAX_GOALS = 10
MAX_FORECAST = 15
MAX_CATEGORIES_PER_CURRENCY = 5
RECENT_FULL_MONTHS = 3
CHARS_PER_TOKEN = 3  # грубая оценка для кириллицы и цифр, без токенизатора

QUALITY_TEXT = {
    "inactive_account_nonzero_balance": "на неактивном счёте есть остаток; он не входит в итоги",
    "label_sanitized": "название очищено от служебных символов",
    "list_truncated": "часть длинного списка не показана",
    "recurring_past_unprocessed": "есть прошедшие даты регулярных операций, которые ещё не обработаны (это не просрочка платежа)",
    "recurring_timezone_ambiguous": "некоторые даты регулярных операций неоднозначны из-за разницы UTC и местного времени",
    "local_and_utc_dates_differ": "местная дата и дата UTC сейчас различаются",
    "debt_without_due_date": "есть долги без срока погашения",
}
NULL_REASON_TEXT = {
    "no_expense_previous_month": "в предыдущем месяце не было расходов",
    "no_transactions_in_window": "в окне наблюдения нет операций",
    "no_income_last_month": "в прошлом месяце не было доходов",
    "no_income_in_window": "в окне наблюдения нет доходов",
    "zero_budget_limit": "лимит бюджета равен нулю",
    "no_target_date": "срок цели не задан",
    "target_date_passed": "срок цели уже прошёл",
    "goal_completed": "цель достигнута",
    "goal_archived": "цель в архиве",
}
BUDGET_STATUS_TEXT = {"ok": "в пределах лимита", "warning": "близко к лимиту (80% и больше)", "exceeded": "лимит превышен"}
DUE_STATE_TEXT = {
    "none": "срок не задан",
    "upcoming": "срок впереди",
    "soon": "срок скоро",
    "today": "срок сегодня",
    "overdue": "срок прошёл (просрочен)",
    "paid": "погашен",
}
DIRECTION_TEXT = {"i_owe": "я должен", "owed_to_me": "мне должны"}
GOAL_STATUS_TEXT = {"active": "в процессе", "completed": "достигнута", "archived": "в архиве"}
FORECAST_STATUS_TEXT = {
    "upcoming": "запланировано",
    "due_today": "сегодня",
    "timezone_ambiguous": "дата неоднозначна из-за UTC и местного времени — не считать просрочкой",
    "past_unprocessed": "дата прошла, операция ещё не создана — не считать просрочкой платежа",
}
MONTHS_RU = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]


# --- структура -------------------------------------------------------------------


def money(out: MoneyOut) -> DigestMoney:
    return DigestMoney(minor=out.minor, currency=out.currency, display=Money.of(out.minor, out.currency).format())


def _cap(items: list, limit: int, name: str, truncated: list[str]) -> list:
    if len(items) > limit:
        truncated.append(name)
    return items[:limit]


def build_digest(ctx: FinancialContextOut) -> AssistantDigest:
    truncated: list[str] = []
    meta = ctx.meta

    quality = [
        DigestQualityNote(code=q.code, text=QUALITY_TEXT[q.code], count=q.count)
        for q in ctx.data_quality
        if q.code != "label_sanitized"  # технический код, модели не нужен
    ]

    indicators = [
        DigestIndicators(
            currency=i.currency,
            income_last_month=money(i.income_last_month),
            expense_last_month=money(i.expense_last_month),
            net_last_month=money(i.net_last_month),
            expense_change_percent=i.expense_change_percent.value,
            expense_change_null_reason=i.expense_change_percent.null_reason,
            avg_monthly_income=money(i.avg_monthly_income.value) if i.avg_monthly_income.value else None,
            avg_monthly_expense=money(i.avg_monthly_expense.value) if i.avg_monthly_expense.value else None,
            window_months=i.avg_monthly_income.window_months,
            months_with_income=i.avg_monthly_income.months_with_transactions,
            months_with_expense=i.avg_monthly_expense.months_with_transactions,
            savings_rate_percent=i.savings_rate_percent.value,
            savings_rate_null_reason=i.savings_rate_percent.null_reason,
            active_accounts_net_position=money(i.active_accounts_net_position),
            debt_to_avg_monthly_income=i.debt_to_avg_monthly_income.value,
            debt_ratio_null_reason=i.debt_to_avg_monthly_income.null_reason,
            overdue_debts=i.overdue_debts,
            debt_deadlines_in_horizon=i.debt_deadlines_in_horizon,
        )
        for i in ctx.indicators.by_currency
    ]

    active_accounts = [a for a in ctx.accounts.items if a.is_active]
    accounts = [
        DigestAccount(label=a.label, currency=a.currency, balance=money(a.balance))
        for a in _cap(active_accounts, MAX_ACCOUNTS, "accounts", truncated)
    ]

    # Сначала превышенные и близкие к лимиту — они важнее для ответа.
    budget_order = {"exceeded": 0, "warning": 1, "ok": 2}
    budget_items = sorted(ctx.budgets.items, key=lambda b: (budget_order[b.status], -b.usage_percent, b.id))
    budgets = [
        DigestBudget(
            label=b.label,
            currency=b.amount.currency,
            limit=money(b.amount),
            spent=money(b.spent),
            remaining=money(b.remaining),
            usage_percent=b.usage_percent,
            status=b.status,
        )
        for b in _cap(budget_items, MAX_BUDGETS, "budgets", truncated)
    ]

    debts = [
        DigestDebt(
            label=d.label,
            direction=d.direction,
            currency=d.remaining.currency,
            remaining=money(d.remaining),
            paid_percent=d.paid_percent,
            due_date=d.due_date,
            due_state=d.due_state,
            days_until_due=d.days_until_due,
        )
        for d in _cap(ctx.debts.open, MAX_DEBTS, "debts", truncated)  # уже по сроку
    ]

    goals = [
        DigestGoal(
            label=g.label,
            status=g.status,
            currency=g.target.currency,
            target=money(g.target),
            saved=money(g.saved),
            remaining=money(g.remaining),
            progress_percent=g.progress_percent,
            target_date=g.target_date,
            months_left=g.months_left,
            required_monthly=money(g.required_monthly) if g.required_monthly else None,
            plan_null_reason=g.plan_null_reason,
        )
        for g in _cap([g for g in ctx.goals.items if g.status != "archived"], MAX_GOALS, "goals", truncated)
    ]

    forecast_src = ctx.upcoming.recurring_forecast
    forecast = [
        DigestForecastItem(
            label=f.label, flow=f.flow, occurs_on=f.occurs_on, date_status=f.date_status, amount=money(f.amount)
        )
        for f in _cap(forecast_src.items, MAX_FORECAST, "recurring_forecast", truncated)
    ]
    if forecast_src.truncated and "recurring_forecast" not in truncated:
        truncated.append("recurring_forecast")
    forecast_totals = [
        DigestForecastTotal(
            currency=t.currency, outflow=money(t.outflow), inflow=money(t.inflow), occurrences=t.occurrences
        )
        for t in forecast_src.totals_by_currency
    ]

    months = [*ctx.cash_flow.full_months[-RECENT_FULL_MONTHS:], ctx.cash_flow.current_month]
    cash_flow = [
        DigestMonthFlow(
            year=m.year,
            month=m.month,
            complete=m.complete,
            currency=f.currency,
            income=money(f.income),
            expense=money(f.expense),
            net=money(f.net),
        )
        for m in months
        for f in m.by_currency
    ]

    categories: list[DigestCategory] = []
    for group in ctx.cash_flow.top_expense_categories_current_month:
        if len(group.items) > MAX_CATEGORIES_PER_CURRENCY or group.truncated:
            truncated.append(f"top_categories:{group.currency}")
        categories.extend(
            DigestCategory(currency=group.currency, label=c.label, amount=money(c.amount), share_percent=c.share_percent)
            for c in group.items[:MAX_CATEGORIES_PER_CURRENCY]
        )

    for name, flag in (
        ("debts", ctx.debts.truncated),
        ("goals", ctx.goals.truncated),
        ("accounts", ctx.accounts.truncated),
    ):
        if flag and name not in truncated:
            truncated.append(name)

    return AssistantDigest(
        meta=DigestMeta(
            context_schema_version=meta.schema_version,
            generated_at=meta.generated_at,
            today=meta.today,
            today_utc=meta.today_utc,
            local_and_utc_dates_differ=meta.local_and_utc_dates_differ,
            base_currency=meta.base_currency,
            currencies=meta.currencies_in_use,
            window_start=meta.window_start,
            window_end=meta.window_end,
            horizon_end=meta.horizon_end,
        ),
        data_quality=quality,
        indicators=indicators,
        accounts=accounts,
        budgets=budgets,
        debts=debts,
        goals=goals,
        recurring_forecast=forecast,
        recurring_forecast_totals=forecast_totals,
        cash_flow=cash_flow,
        top_categories=categories,
        unread_notifications=ctx.notifications.unread,
        truncated_lists=truncated,
    )


# --- текст -----------------------------------------------------------------------


def label(text: str) -> str:
    """Название как строковый литерал: кавычки и спецсимволы экранированы."""
    return json.dumps(text, ensure_ascii=False)


def pct(value: float) -> str:
    return f"{value:.1f}".replace(".", ",") + "%"


def _reason(code: str | None) -> str:
    return NULL_REASON_TEXT.get(code or "", "нет данных")


def _section_overview(d: AssistantDigest) -> list[str]:
    m = d.meta
    lines = [
        f"Сегодня (местная дата): {m.today.isoformat()}; дата UTC: {m.today_utc.isoformat()}.",
        f"Валюты: {', '.join(m.currencies) or 'нет данных'}. Базовая валюта: {m.base_currency}. "
        "Курсов валют нет: суммы в разных валютах нельзя складывать и сравнивать.",
        f"Окно показателей: {m.window_start.isoformat()} — {m.window_end.isoformat()} (полные месяцы, границы по UTC). "
        f"Горизонт предстоящих событий: до {m.horizon_end.isoformat()}.",
    ]
    if m.local_and_utc_dates_differ:
        lines.append("Внимание: местная дата и дата UTC различаются.")
    return lines


def _section_quality(d: AssistantDigest) -> list[str]:
    return [f"- {q.text}" + (f" (количество: {q.count})" if q.count else "") for q in d.data_quality]


def _section_indicators(d: AssistantDigest) -> list[str]:
    lines: list[str] = []
    for i in d.indicators:
        lines.append(f"[{i.currency}]")
        lines.append(
            f"- Прошлый полный месяц: доходы {i.income_last_month.display}, расходы {i.expense_last_month.display}, "
            f"итог {i.net_last_month.display}."
        )
        change = pct(i.expense_change_percent) if i.expense_change_percent is not None else f"нет данных ({_reason(i.expense_change_null_reason)})"
        lines.append(f"- Изменение расходов к предыдущему месяцу: {change}.")
        avg_in = i.avg_monthly_income.display if i.avg_monthly_income else f"нет данных ({_reason('no_transactions_in_window')})"
        avg_out = i.avg_monthly_expense.display if i.avg_monthly_expense else f"нет данных ({_reason('no_transactions_in_window')})"
        lines.append(
            f"- Средний месячный доход: {avg_in}; средний месячный расход: {avg_out} "
            f"(окно {i.window_months} мес.; доходы были в {i.months_with_income}, расходы — в {i.months_with_expense} мес.)."
        )
        savings = pct(i.savings_rate_percent) if i.savings_rate_percent is not None else f"нет данных ({_reason(i.savings_rate_null_reason)})"
        lines.append(f"- Норма сбережений прошлого месяца: {savings}.")
        lines.append(
            f"- Расчётный капитал по активным счетам с учётом открытых долгов: {i.active_accounts_net_position.display} "
            "(не полная стоимость активов)."
        )
        ratio = (
            f"{i.debt_to_avg_monthly_income:.2f}".replace(".", ",")
            if i.debt_to_avg_monthly_income is not None
            else f"нет данных ({_reason(i.debt_ratio_null_reason)})"
        )
        lines.append(
            f"- Долг «я должен» в среднемесячных доходах: {ratio}. Просроченных долгов: {i.overdue_debts}; "
            f"сроков долгов в горизонте: {i.debt_deadlines_in_horizon}."
        )
    return lines


def _section_budgets(d: AssistantDigest) -> list[str]:
    return [
        f"- Бюджет {label(b.label)}: лимит {b.limit.display}, потрачено {b.spent.display} ({pct(b.usage_percent)}), "
        f"остаток {b.remaining.display}; {BUDGET_STATUS_TEXT[b.status]}."
        for b in d.budgets
    ]


def _section_debts(d: AssistantDigest) -> list[str]:
    lines = []
    for x in d.debts:
        due = (
            f"срок {x.due_date.isoformat()}, {DUE_STATE_TEXT.get(x.due_state, x.due_state)}"
            + (f" (дней до срока: {x.days_until_due})" if x.days_until_due is not None else "")
            if x.due_date
            else DUE_STATE_TEXT["none"]
        )
        lines.append(
            f"- Долг {label(x.label)}: {DIRECTION_TEXT[x.direction]}, остаток {x.remaining.display}, "
            f"погашено {pct(x.paid_percent)}; {due}. Графика платежей нет: остаток — это сумма к сроку, а не ежемесячный платёж."
        )
    return lines


def _section_forecast(d: AssistantDigest) -> list[str]:
    lines = [
        f"- {f.occurs_on.isoformat()}: {label(f.label)}, {'поступление' if f.flow == 'in' else 'списание'} "
        f"{f.amount.display}; {FORECAST_STATUS_TEXT[f.date_status]}."
        for f in d.recurring_forecast
    ]
    lines += [
        f"- Итого по прогнозу [{t.currency}]: списания {t.outflow.display}, поступления {t.inflow.display} "
        f"({t.occurrences} операций)."
        for t in d.recurring_forecast_totals
    ]
    return lines


def _section_goals(d: AssistantDigest) -> list[str]:
    lines = []
    for g in d.goals:
        plan = (
            f"до срока {g.target_date.isoformat()} осталось {g.months_left} мес.; чтобы успеть, нужно откладывать "
            f"{g.required_monthly.display} в месяц"
            if g.required_monthly is not None and g.target_date is not None
            else f"план взносов не рассчитан ({_reason(g.plan_null_reason)})"
        )
        lines.append(
            f"- Цель {label(g.label)} ({GOAL_STATUS_TEXT[g.status]}): накоплено {g.saved.display} из {g.target.display} "
            f"({pct(g.progress_percent)}), осталось накопить {g.remaining.display}; {plan}."
        )
    return lines


def _section_accounts(d: AssistantDigest) -> list[str]:
    return [f"- Счёт {label(a.label)}: остаток {a.balance.display}." for a in d.accounts]


def _section_cash_flow(d: AssistantDigest) -> list[str]:
    return [
        f"- {MONTHS_RU[f.month - 1]} {f.year}{'' if f.complete else ' (месяц ещё идёт)'} [{f.currency}]: "
        f"доходы {f.income.display}, расходы {f.expense.display}, итог {f.net.display}."
        for f in d.cash_flow
    ]


def _section_categories(d: AssistantDigest) -> list[str]:
    return [
        f"- [{c.currency}] {label(c.label)}: {c.amount.display} ({pct(c.share_percent)} расходов месяца)."
        for c in d.top_categories
    ]


def _section_notifications(d: AssistantDigest) -> list[str]:
    return [f"- Непрочитанных уведомлений: {d.unread_notifications}."]


# Порядок — это и приоритет: при нехватке бюджета пропускаются последние.
SECTIONS = [
    ("overview", "Общие сведения", _section_overview),
    ("data_quality", "Особенности данных", _section_quality),
    ("indicators", "Показатели по валютам", _section_indicators),
    ("budgets", "Бюджеты текущего месяца", _section_budgets),
    ("debts", "Открытые долги", _section_debts),
    ("recurring_forecast", "Регулярные операции: прогноз на горизонт", _section_forecast),
    ("goals", "Цели", _section_goals),
    ("accounts", "Активные счета", _section_accounts),
    ("cash_flow", "Доходы и расходы по месяцам", _section_cash_flow),
    ("top_categories", "Крупнейшие категории расходов текущего месяца", _section_categories),
    ("notifications", "Уведомления", _section_notifications),
]


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def render_digest_text(digest: AssistantDigest, token_budget: int) -> tuple[str, int, list[str]]:
    """Текст сводки в пределах бюджета токенов.

    Разделы добавляются по приоритету; раздел, который не помещается,
    пропускается целиком (с пометкой), а не обрезается посередине — чтобы
    модель не видела половину списка как будто весь список. Первый раздел
    «Общие сведения» включается всегда."""
    blocks: list[str] = []
    omitted: list[str] = []
    for key, title, render in SECTIONS:
        lines = render(digest)
        if not lines:
            continue
        block = f"## {title}\n" + "\n".join(lines)
        candidate = "\n\n".join([*blocks, block])
        if blocks and estimate_tokens(candidate) > token_budget:
            omitted.append(key)
            continue
        blocks.append(block)
    if omitted:
        blocks.append("## Не поместилось в сводку\n- Разделы опущены из-за размера: " + ", ".join(omitted) + ".")
    text = "\n\n".join(blocks)
    return text, estimate_tokens(text), omitted
