"""Сборка финансового контекста (Stage 2F).

Только чтение: модуль выполняет SELECT и вызывает существующие расчётные
функции (compute_balance, to_out долгов/бюджетов/целей, engine/*), чтобы
цифры контекста совпадали с экранами приложения. Финансовые правила здесь не
переопределяются.

Из существующих DTO берутся только поля без свободного текста: комментарии и
описания (DebtOut.comment, GoalOut.description, RecurringTransactionOut.comment)
в контекст не попадают. Пользовательские названия проходят sanitize_label и
считаются недоверенными данными.

Даты: «сегодня» — локальная дата (clock.today), календарные месяцы — в UTC
(month_bounds, как у бюджетов), номер текущего месяца — по локальной дате.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.accounts import compute_balance
from app.api.v1.budgets import to_out as budget_to_out
from app.api.v1.debts import to_out as debt_to_out
from app.api.v1.goals import to_out as goal_to_out
from app.context import indicators as ind
from app.context.labels import sanitize_label
from app.db.models import (
    Account,
    Budget,
    Category,
    Debt,
    Goal,
    Notification,
    RecurringTransaction,
    Transaction,
)
from app.db.models.app_settings import get_base_currency
from app.engine.analytics import share_percent
from app.engine.budgets import month_bounds
from app.engine.flows import is_transfer
from app.engine.money import Money, get_currency, money_sum
from app.engine.recurring import pending_occurrences
from app.notifications.rules import previous_month
from app.schemas.context import (
    FINANCIAL_CONTEXT_VERSION,
    UNTRUSTED_TEXT_FIELDS,
    AccountItemOut,
    AccountsOut,
    AccountTotalOut,
    AverageIndicatorOut,
    BudgetItemOut,
    BudgetsOut,
    BudgetSummaryOut,
    CashFlowOut,
    CategorySpendOut,
    ConventionsOut,
    CurrencyCategoriesOut,
    CurrencyIndicatorsOut,
    DataQualityItemOut,
    DebtDeadlineOut,
    DebtDeadlinesOut,
    DebtItemOut,
    DebtsOut,
    DebtTotalOut,
    FinancialContextOut,
    FlowOut,
    ForecastItemOut,
    ForecastTotalOut,
    GoalItemOut,
    GoalsOut,
    IndicatorsOut,
    MetaOut,
    MonthFlowOut,
    NotificationsSummaryOut,
    PercentIndicatorOut,
    RatioIndicatorOut,
    RecurringForecastOut,
    RecurringItemOut,
    RecurringOut,
    UpcomingOut,
)
from app.schemas.money import MoneyOut

MAX_ACCOUNTS = 100
MAX_DEBTS = 100
MAX_GOALS = 100
MAX_RECURRING = 100
MAX_TOP_CATEGORIES = 10
MAX_DEBT_DEADLINES = 50
MAX_FORECAST_ITEMS = 50


def _out(money: Money) -> MoneyOut:
    return MoneyOut(minor=money.minor, currency=money.currency.code)


def _money(out: MoneyOut) -> Money:
    return Money.of(out.minor, out.currency)


def _month_list(year: int, month: int, count: int) -> list[tuple[int, int]]:
    """count полных месяцев перед (year, month), от старого к новому."""
    months: list[tuple[int, int]] = []
    y, m = year, month
    for _ in range(count):
        y, m = previous_month(y, m)
        months.append((y, m))
    return list(reversed(months))


@dataclass
class _Flow:
    """Доходы и расходы одной валюты за один месяц."""

    currency: str
    income: Money
    expense: Money
    income_count: int = 0
    expense_count: int = 0

    @classmethod
    def empty(cls, currency: str) -> "_Flow":
        return cls(currency, Money.zero(currency), Money.zero(currency))

    def to_out(self) -> FlowOut:
        return FlowOut(
            currency=self.currency,
            income=_out(self.income),
            expense=_out(self.expense),
            net=_out(self.income - self.expense),
            transactions=self.income_count + self.expense_count,
        )


@dataclass
class _Collector:
    """Метки и записи data_quality, накопленные по ходу сборки."""

    sanitized: set[tuple[str, int]] = field(default_factory=set)
    quality: list[DataQualityItemOut] = field(default_factory=list)

    def label(self, entity: str, entity_id: int, raw: str | None) -> str:
        text, changed = sanitize_label(raw)
        if changed:
            self.sanitized.add((entity, entity_id))
        return text

    def truncated(self, entity: str, total: int, limit: int) -> bool:
        if total <= limit:
            return False
        self.quality.append(DataQualityItemOut(code="list_truncated", entity=entity, count=total))
        return True


def build_context(
    db: Session,
    *,
    months: int,
    horizon_days: int,
    today: date,
    today_utc: date,
    now: datetime,
) -> FinancialContextOut:
    c = _Collector()
    base_currency = get_currency(get_base_currency(db)).code
    categories = {cat.id: cat for cat in db.scalars(select(Category))}

    # --- периоды -------------------------------------------------------------
    full_months = _month_list(today.year, today.month, months)
    last_full = full_months[-1]
    prev_of_last = previous_month(*last_full)
    fetch_first = full_months[0] if months >= 2 else prev_of_last
    fetch_start, _ = month_bounds(*fetch_first)
    current_start, current_end = month_bounds(today.year, today.month)
    window_start, _ = month_bounds(*full_months[0])
    _, window_end = month_bounds(*last_full)
    horizon_end = today + timedelta(days=horizon_days)

    # --- операции: потоки по месяцам и валютам ------------------------------
    flows: dict[tuple[int, int], dict[str, _Flow]] = defaultdict(dict)
    current_expense_by_category: dict[str, dict[int, Money]] = defaultdict(dict)
    tx_currencies: set[str] = set()
    for t in db.scalars(
        select(Transaction).where(
            Transaction.occurred_at >= fetch_start, Transaction.occurred_at <= current_end
        )
    ):
        if is_transfer(t):  # отмеченный пользователем перевод — не доход и не расход
            continue
        at = t.occurred_at.astimezone(timezone.utc)
        key = (at.year, at.month)
        flow = flows[key].setdefault(t.currency, _Flow.empty(t.currency))
        amount = Money.of(t.amount_minor, t.currency)
        tx_currencies.add(t.currency)
        if t.type == "income":
            flow.income = flow.income + amount
            flow.income_count += 1
        else:
            flow.expense = flow.expense + amount
            flow.expense_count += 1
            if key == (today.year, today.month):
                per_cat = current_expense_by_category[t.currency]
                per_cat[t.category_id] = per_cat.get(t.category_id, Money.zero(t.currency)) + amount

    def month_out(y: int, m: int, complete: bool) -> MonthFlowOut:
        return MonthFlowOut(
            year=y,
            month=m,
            complete=complete,
            by_currency=[flows[(y, m)][cur].to_out() for cur in sorted(flows.get((y, m), {}))],
        )

    top_categories: list[CurrencyCategoriesOut] = []
    current_flows = flows.get((today.year, today.month), {})
    for cur in sorted(current_expense_by_category):
        total = current_flows[cur].expense
        ranked = sorted(current_expense_by_category[cur].items(), key=lambda kv: (-kv[1].minor, kv[0]))
        items = [
            CategorySpendOut(
                category_id=cat_id,
                label=c.label("category", cat_id, categories[cat_id].name if cat_id in categories else ""),
                amount=_out(amount),
                share_percent=ind.round_percent(share_percent(amount, total)) or 0.0,
            )
            for cat_id, amount in ranked[:MAX_TOP_CATEGORIES]
        ]
        top_categories.append(
            CurrencyCategoriesOut(currency=cur, items=items, truncated=len(ranked) > MAX_TOP_CATEGORIES)
        )

    cash_flow = CashFlowOut(
        current_month=month_out(today.year, today.month, complete=False),
        full_months=[month_out(y, m, complete=True) for y, m in full_months],
        top_expense_categories_current_month=top_categories,
    )

    first_tx_dates = {
        cur: first.astimezone(timezone.utc).date()
        for cur, first in db.execute(
            select(Transaction.currency, func.min(Transaction.occurred_at)).group_by(Transaction.currency)
        )
        if first is not None
    }

    # --- счета ---------------------------------------------------------------
    accounts = list(db.scalars(select(Account).order_by(Account.id)))
    account_items: list[AccountItemOut] = []
    active_balances: dict[str, list[Money]] = defaultdict(list)
    for a in accounts:
        balance = compute_balance(db, a)
        if a.is_active:
            active_balances[a.currency].append(balance)
        elif balance.minor != 0:
            c.quality.append(
                DataQualityItemOut(
                    code="inactive_account_nonzero_balance",
                    entity="account",
                    id=a.id,
                    currency=a.currency,
                    amount=_out(balance),
                )
            )
        account_items.append(
            AccountItemOut(
                id=a.id,
                label=c.label("account", a.id, a.name),
                type=a.type,  # type: ignore[arg-type]
                currency=a.currency,
                is_active=a.is_active,
                balance=_out(balance),
            )
        )
    active_totals = {cur: money_sum(items, cur) for cur, items in active_balances.items()}
    accounts_out = AccountsOut(
        items=account_items[:MAX_ACCOUNTS],
        active_totals_by_currency=[
            AccountTotalOut(currency=cur, balance=_out(active_totals[cur]), active_accounts=len(active_balances[cur]))
            for cur in sorted(active_totals)
        ],
        truncated=c.truncated("account", len(account_items), MAX_ACCOUNTS),
    )

    # --- долги ---------------------------------------------------------------
    open_debts: list[DebtItemOut] = []
    paid_count = 0
    without_due_date = 0
    for d in db.scalars(select(Debt).order_by(Debt.id)):
        out = debt_to_out(d, today)  # те же правила, что у экрана «Долги»
        if out.status == "paid":
            paid_count += 1
            continue
        if out.due_date is None:
            without_due_date += 1
        open_debts.append(
            DebtItemOut(
                id=out.id,
                label=c.label("debt", out.id, out.counterparty_name),
                direction=out.direction,
                status=out.status,
                principal=out.principal,
                paid=out.paid,
                remaining=out.remaining,
                paid_percent=out.paid_percent,
                due_date=out.due_date,
                due_state=out.due_state,
                days_until_due=out.days_until_due,
            )
        )
    open_debts.sort(key=lambda x: (x.due_date is None, x.due_date or date.max, x.id))
    if without_due_date:
        c.quality.append(DataQualityItemOut(code="debt_without_due_date", entity="debt", count=without_due_date))

    i_owe: dict[str, list[Money]] = defaultdict(list)
    owed_to_me: dict[str, list[Money]] = defaultdict(list)
    for x in open_debts:
        (i_owe if x.direction == "i_owe" else owed_to_me)[x.remaining.currency].append(_money(x.remaining))
    debt_currencies = sorted(set(i_owe) | set(owed_to_me))
    debt_totals = {
        cur: (money_sum(i_owe.get(cur, []), cur), money_sum(owed_to_me.get(cur, []), cur)) for cur in debt_currencies
    }
    debts_out = DebtsOut(
        open=open_debts[:MAX_DEBTS],
        paid_count=paid_count,
        overdue_count=sum(1 for x in open_debts if x.due_state == "overdue"),
        totals_by_currency=[
            DebtTotalOut(currency=cur, i_owe=_out(debt_totals[cur][0]), owed_to_me=_out(debt_totals[cur][1]))
            for cur in debt_currencies
        ],
        truncated=c.truncated("debt", len(open_debts), MAX_DEBTS),
    )

    deadlines = [x for x in open_debts if x.due_date is not None and x.due_date <= horizon_end]
    debt_deadlines = DebtDeadlinesOut(
        items=[
            DebtDeadlineOut(
                debt_id=x.id,
                label=x.label,
                direction=x.direction,
                due_date=x.due_date,  # type: ignore[arg-type]
                due_state=x.due_state,
                days_until_due=x.days_until_due,  # type: ignore[arg-type]
                remaining=x.remaining,
            )
            for x in deadlines[:MAX_DEBT_DEADLINES]
        ],
        truncated=c.truncated("debt", len(deadlines), MAX_DEBT_DEADLINES),
    )

    # --- бюджеты текущего месяца ---------------------------------------------
    budget_items: list[BudgetItemOut] = []
    for b in db.scalars(
        select(Budget).where(Budget.year == today.year, Budget.month == today.month).order_by(Budget.id)
    ):
        out = budget_to_out(db, b)  # тот же расчёт, что у экрана «Бюджеты»
        budget_items.append(
            BudgetItemOut(
                id=out.id,
                category_id=out.category_id,
                label=c.label("budget", out.id, out.category_name),
                amount=out.amount,
                spent=out.spent,
                remaining=out.remaining,
                usage_percent=out.usage_percent,
                status=out.status,
            )
        )
    budget_summaries: list[BudgetSummaryOut] = []
    for cur in sorted({x.amount.currency for x in budget_items}):
        group = [x for x in budget_items if x.amount.currency == cur]
        limit = money_sum((_money(x.amount) for x in group), cur)
        spent = money_sum((_money(x.spent) for x in group), cur)
        usage, reason = ind.budget_usage_percent(spent, limit)
        budget_summaries.append(
            BudgetSummaryOut(
                currency=cur,
                budgets=len(group),
                limit=_out(limit),
                spent=_out(spent),
                usage_percent=usage,
                usage_percent_null_reason=reason,  # type: ignore[arg-type]
                warning=sum(1 for x in group if x.status == "warning"),
                exceeded=sum(1 for x in group if x.status == "exceeded"),
            )
        )
    budgets_out = BudgetsOut(
        year=today.year, month=today.month, items=budget_items, summary_by_currency=budget_summaries
    )

    # --- цели ----------------------------------------------------------------
    goal_items: list[GoalItemOut] = []
    for g in db.scalars(select(Goal).order_by(Goal.id)):
        out = goal_to_out(g)  # описание цели (свободный текст) не берётся
        months_to_go, required, reason = ind.goal_plan(out.status, _money(out.remaining), out.target_date, today)
        goal_items.append(
            GoalItemOut(
                id=out.id,
                label=c.label("goal", out.id, out.name),
                status=out.status,
                target=out.target,
                saved=out.saved,
                remaining=out.remaining,
                progress_percent=out.progress_percent,
                target_date=out.target_date,
                months_left=months_to_go,
                required_monthly=_out(required) if required is not None else None,
                plan_null_reason=reason,  # type: ignore[arg-type]
            )
        )
    goals_out = GoalsOut(items=goal_items[:MAX_GOALS], truncated=c.truncated("goal", len(goal_items), MAX_GOALS))

    # --- регулярные операции и прогноз ----------------------------------------
    rules = list(
        db.scalars(
            select(RecurringTransaction).where(RecurringTransaction.is_active.is_(True)).order_by(RecurringTransaction.id)
        )
    )
    recurring_items: list[RecurringItemOut] = []
    forecast: list[ForecastItemOut] = []
    for r in rules:
        category_label = c.label("category", r.category_id, r.category.name)
        recurring_items.append(
            RecurringItemOut(
                id=r.id,
                type=r.type,  # type: ignore[arg-type]
                account_id=r.account_id,
                account_label=c.label("account", r.account_id, r.account.name),
                category_id=r.category_id,
                category_label=category_label,
                amount=MoneyOut(minor=r.amount_minor, currency=r.currency),
                frequency=r.frequency,  # type: ignore[arg-type]
                next_run_date=r.next_run_date,
                end_date=r.end_date,
            )
        )
        # Та же функция, что генерирует операции при обработке правил: даты
        # от next_run_date до конца горизонта с учётом end_date.
        dates, _, _ = pending_occurrences(r.next_run_date, horizon_end, r.frequency, r.end_date)  # type: ignore[arg-type]
        for d in dates:
            forecast.append(
                ForecastItemOut(
                    rule_id=r.id,
                    label=category_label,
                    type=r.type,  # type: ignore[arg-type]
                    flow="in" if r.type == "income" else "out",
                    occurs_on=d,
                    date_status=ind.forecast_date_status(d, today, today_utc),  # type: ignore[arg-type]
                    amount=MoneyOut(minor=r.amount_minor, currency=r.currency),
                )
            )
    forecast.sort(key=lambda x: (x.occurs_on, x.rule_id))
    forecast_totals: list[ForecastTotalOut] = []
    for cur in sorted({x.amount.currency for x in forecast}):
        group = [x for x in forecast if x.amount.currency == cur]
        forecast_totals.append(
            ForecastTotalOut(
                currency=cur,
                outflow=_out(money_sum((_money(x.amount) for x in group if x.flow == "out"), cur)),
                inflow=_out(money_sum((_money(x.amount) for x in group if x.flow == "in"), cur)),
                occurrences=len(group),
            )
        )
    past_unprocessed = sum(1 for x in forecast if x.date_status == "past_unprocessed")
    ambiguous = sum(1 for x in forecast if x.date_status == "timezone_ambiguous")
    if past_unprocessed:
        c.quality.append(
            DataQualityItemOut(code="recurring_past_unprocessed", entity="recurring_transaction", count=past_unprocessed)
        )
    if ambiguous:
        c.quality.append(
            DataQualityItemOut(code="recurring_timezone_ambiguous", entity="recurring_transaction", count=ambiguous)
        )
    recurring_out = RecurringOut(
        active=recurring_items[:MAX_RECURRING],
        truncated=c.truncated("recurring_transaction", len(recurring_items), MAX_RECURRING),
    )
    upcoming = UpcomingOut(
        horizon_days=horizon_days,
        horizon_end=horizon_end,
        debt_deadlines=debt_deadlines,
        recurring_forecast=RecurringForecastOut(
            items=forecast[:MAX_FORECAST_ITEMS],
            totals_by_currency=forecast_totals,
            past_unprocessed=past_unprocessed,
            timezone_ambiguous=ambiguous,
            truncated=c.truncated("recurring_transaction", len(forecast), MAX_FORECAST_ITEMS),
        ),
    )

    # --- показатели по валютам ------------------------------------------------
    currencies = sorted(
        {a.currency for a in accounts}
        | tx_currencies
        | set(debt_currencies)
        | {x.amount.currency for x in budget_items}
        | {x.target.currency for x in goal_items}
        | {r.currency for r in rules}
    )
    indicators: list[CurrencyIndicatorsOut] = []
    for cur in currencies:

        def flow(key: tuple[int, int], cur: str = cur) -> _Flow:
            return flows.get(key, {}).get(cur) or _Flow.empty(cur)

        last, prev = flow(last_full), flow(prev_of_last)
        change, change_reason = ind.expense_change_percent(last.expense, prev.expense)
        window = [flow(k) for k in full_months]
        avg_income = ind.monthly_average(
            [f.income for f in window], sum(1 for f in window if f.income_count), cur
        )
        avg_expense = ind.monthly_average(
            [f.expense for f in window], sum(1 for f in window if f.expense_count), cur
        )
        savings, savings_reason = ind.savings_rate_percent(last.income, last.expense)
        i_owe_total, owed_total = debt_totals.get(cur, (Money.zero(cur), Money.zero(cur)))
        net_position = active_totals.get(cur, Money.zero(cur)) + owed_total - i_owe_total
        ratio, ratio_reason = ind.debt_to_avg_monthly_income(i_owe_total, avg_income.value)
        indicators.append(
            CurrencyIndicatorsOut(
                currency=cur,
                first_transaction_date=first_tx_dates.get(cur),
                income_last_month=_out(last.income),
                expense_last_month=_out(last.expense),
                net_last_month=_out(last.income - last.expense),
                expense_change_percent=PercentIndicatorOut(value=change, null_reason=change_reason),  # type: ignore[arg-type]
                avg_monthly_income=_average_out(avg_income),
                avg_monthly_expense=_average_out(avg_expense),
                savings_rate_percent=PercentIndicatorOut(value=savings, null_reason=savings_reason),  # type: ignore[arg-type]
                active_accounts_net_position=_out(net_position),
                debt_to_avg_monthly_income=RatioIndicatorOut(value=ratio, null_reason=ratio_reason),  # type: ignore[arg-type]
                overdue_debts=sum(
                    1 for x in open_debts if x.remaining.currency == cur and x.due_state == "overdue"
                ),
                debt_deadlines_in_horizon=sum(1 for x in deadlines if x.remaining.currency == cur),
            )
        )

    # --- уведомления: только счётчики, без текстов ----------------------------
    visible = Notification.deleted_at.is_(None) & Notification.resolved_at.is_(None)
    unread = db.scalar(select(func.count(Notification.id)).where(visible & Notification.read_at.is_(None))) or 0
    active_by_type = {
        t: n
        for t, n in db.execute(
            select(Notification.type, func.count(Notification.id)).where(visible).group_by(Notification.type)
        )
    }

    # --- data quality и meta --------------------------------------------------
    if today != today_utc:
        c.quality.append(DataQualityItemOut(code="local_and_utc_dates_differ", entity="context"))
    for entity, entity_id in sorted(c.sanitized):
        c.quality.append(DataQualityItemOut(code="label_sanitized", entity=entity, id=entity_id))  # type: ignore[arg-type]

    meta = MetaOut(
        schema_version=FINANCIAL_CONTEXT_VERSION,
        generated_at=now,
        today=today,
        today_utc=today_utc,
        local_and_utc_dates_differ=today != today_utc,
        base_currency=base_currency,
        currencies_in_use=currencies,
        months_window=months,
        window_start=window_start.date(),
        window_end=window_end.date(),
        horizon_days=horizon_days,
        horizon_end=horizon_end,
        conventions=ConventionsOut(),
        untrusted_text_fields=list(UNTRUSTED_TEXT_FIELDS),
    )
    return FinancialContextOut(
        meta=meta,
        accounts=accounts_out,
        cash_flow=cash_flow,
        debts=debts_out,
        budgets=budgets_out,
        goals=goals_out,
        recurring=recurring_out,
        upcoming=upcoming,
        indicators=IndicatorsOut(by_currency=indicators),
        notifications=NotificationsSummaryOut(unread=unread, active_by_type=dict(sorted(active_by_type.items()))),
        data_quality=c.quality,
    )


def _average_out(avg: ind.Average) -> AverageIndicatorOut:
    return AverageIndicatorOut(
        value=_out(avg.value) if avg.value is not None else None,
        null_reason=avg.null_reason,  # type: ignore[arg-type]
        window_months=avg.window_months,
        months_with_transactions=avg.months_with_transactions,
    )
