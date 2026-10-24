import { useQuery } from "@tanstack/react-query";
import { Children, type ReactNode } from "react";
import { HandCoins } from "lucide-react";
import { Link } from "react-router-dom";

import { AccountTypeIcon } from "@/lib/accountIcons";
import { Badge } from "@/components/ui/Badge";
import { Card, CardHeader, EmptyState } from "@/components/ui/Card";
import { CategoryIcon } from "@/lib/categoryIcons";
import { analyticsApi } from "@/lib/api/analytics";
import type { Account } from "@/lib/api/accounts";
import type { Budget } from "@/lib/api/budgets";
import { budgetsApi } from "@/lib/api/budgets";
import { dashboardApi, type DebtsSummary, type RecentTransaction } from "@/lib/api/dashboard";
import type { CategorySpending } from "@/lib/api/dashboard";
import { goalsApi, type Goal } from "@/lib/api/goals";
import { BUDGET_STATUS_BAR_CLASS } from "@/lib/budgetStatus";
import { debtDueLabel, sortDebts } from "@/lib/debtDue";
import { computePeriod, periodToApiParams } from "@/lib/period";
import type { MoneyAmount } from "@/lib/money";
import { formatMoney } from "@/lib/money";

import { TimeseriesChart } from "../analytics/TimeseriesChart";

const ACCOUNT_TYPE_LABEL: Record<Account["type"], string> = {
  bank: "Банковский счёт",
  cash: "Наличные",
  other: "Другое",
};

const DASHBOARD_LIST_LIMIT = 4;

function IconTile({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-hover text-ink-500">
      {children}
    </div>
  );
}

/** Ряд блоков, который подстраивается под число реально отрисованных
 * карточек: две — в две колонки, одна — на всю ширину, ни одной — ничего.
 * Пустых плейсхолдеров нет. */
function AdaptiveRow({ children }: { children: ReactNode }) {
  const blocks = Children.toArray(children);
  if (blocks.length === 0) return null;
  return (
    <div
      data-testid="dashboard-row"
      data-blocks={blocks.length}
      className={blocks.length >= 2 ? "grid gap-6 lg:grid-cols-2" : "grid gap-6"}
    >
      {blocks}
    </div>
  );
}

function StatChip({ label, value }: { label: string; value: number }) {
  return (
    <span className="flex items-baseline gap-1.5 text-sm text-ink-500">
      <span className="tabular text-[15px] font-semibold text-ink-900">{value}</span>
      {label}
    </span>
  );
}

function NetWorthCard({
  amount,
  accountCount,
  activeDebtCount,
  budgetCount,
  activeGoalCount,
}: {
  amount: MoneyAmount;
  accountCount: number;
  activeDebtCount: number;
  budgetCount: number;
  activeGoalCount: number;
}) {
  const tone = amount.minor < 0 ? "text-danger" : "text-ink-900";
  return (
    <Card className="bg-gradient-to-br from-white to-page">
      <p className="text-sm font-medium uppercase tracking-[0.12em] text-ink-500">
        Общий капитал
      </p>
      <p className={`tabular mt-3 text-5xl font-semibold tracking-tight ${tone}`}>
        {formatMoney(amount)}
      </p>
      <div className="mt-5 flex flex-wrap gap-x-8 gap-y-2 border-t border-border pt-4">
        <StatChip label="счетов" value={accountCount} />
        <StatChip label="активных долгов" value={activeDebtCount} />
        <StatChip label="бюджетов в этом месяце" value={budgetCount} />
        <StatChip label="активных целей" value={activeGoalCount} />
      </div>
    </Card>
  );
}

function AccountsBlock({ accounts }: { accounts: Account[] }) {
  return (
    <Card>
      <CardHeader
        title="Счета"
        action={
          <Link to="/accounts" className="text-sm font-medium text-accent hover:underline">
            Все счета →
          </Link>
        }
      />
      {accounts.length === 0 ? (
        <EmptyState>Счетов пока нет — добавьте первый на странице «Счета».</EmptyState>
      ) : (
        <ul className="divide-y divide-border">
          {accounts.slice(0, DASHBOARD_LIST_LIMIT).map((a) => (
            <li key={a.id} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
              <IconTile>
                <AccountTypeIcon type={a.type} />
              </IconTile>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[15px] font-medium text-ink-900">{a.name}</p>
                <p className="text-xs text-ink-500">{ACCOUNT_TYPE_LABEL[a.type]}</p>
              </div>
              <span
                className={`tabular text-[15px] font-semibold ${a.balance.minor < 0 ? "text-danger" : "text-ink-900"}`}
              >
                {formatMoney(a.balance)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function DebtsBlock({ summary }: { summary: DebtsSummary }) {
  // Порядок с backend: просроченные и ближайшие сроки сверху, без срока — в конце.
  const shown = sortDebts(summary.items, "urgency").slice(0, DASHBOARD_LIST_LIMIT);
  return (
    <Card>
      <CardHeader
        title="Долги"
        action={
          <Link to="/debts" className="text-sm font-medium text-accent hover:underline">
            Все долги →
          </Link>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm text-ink-500">
        <span>
          Активных: <span className="font-semibold text-ink-900">{summary.items.length}</span>
        </span>
        {summary.overdue_count > 0 && <Badge tone="danger">Просрочено: {summary.overdue_count}</Badge>}
      </div>
      {/* Остатки по каждой валюте отдельно: разные валюты не складываются. */}
      <ul className="mb-4 flex flex-col gap-1 text-sm" data-testid="debt-totals">
        {summary.totals_by_currency.map((t) => (
          <li key={t.currency} className="flex flex-wrap gap-x-5 text-ink-500">
            <span className="w-10 font-medium text-ink-700">{t.currency}</span>
            {t.i_owe.minor > 0 && (
              <span>
                Я должен: <span className="tabular font-semibold text-danger">{formatMoney(t.i_owe)}</span>
              </span>
            )}
            {t.owed_to_me.minor > 0 && (
              <span>
                Мне должны: <span className="tabular font-semibold text-success">{formatMoney(t.owed_to_me)}</span>
              </span>
            )}
          </li>
        ))}
      </ul>
      <ul className="divide-y divide-border">
        {shown.map((d) => (
          <li key={d.id} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
            <div className="min-w-0 flex-1">
              <Link to={`/debts/${d.id}`} className="block truncate text-[15px] font-medium text-ink-900 hover:text-accent">
                {d.counterparty_name}
              </Link>
              <p className="mt-0.5 flex items-center gap-2 text-xs text-ink-500">
                {d.direction === "i_owe" ? "Я должен" : "Должны мне"}
                <Badge tone={debtDueLabel(d).tone}>{debtDueLabel(d).label}</Badge>
              </p>
            </div>
            <span className="tabular text-[15px] font-semibold text-ink-900">{formatMoney(d.remaining)}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function RecentTransactionsBlock({ items }: { items: RecentTransaction[] }) {
  return (
    <Card>
      <CardHeader
        title="Последние операции"
        action={
          <Link to="/transactions" className="text-sm font-medium text-accent hover:underline">
            Все операции →
          </Link>
        }
      />
      {items.length === 0 ? (
        <EmptyState>Операций пока нет.</EmptyState>
      ) : (
        <ul className="divide-y divide-border">
          {items.map((t) => (
            <li key={t.id} className="flex items-center gap-3 py-3.5 first:pt-0 last:pb-0">
              <IconTile>
                {t.debt_id ? (
                  <HandCoins className="h-4 w-4" strokeWidth={1.75} />
                ) : (
                  <CategoryIcon name={t.category_name} type={t.type} icon={t.category_icon} />
                )}
              </IconTile>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[15px] font-medium text-ink-900">
                  {t.category_name}
                </p>
                <p className="truncate text-sm text-ink-500">
                  {t.debt_name && <>Долг: {t.debt_name} · </>}
                  {t.account_name}
                </p>
              </div>
              <span
                className={`tabular text-[15px] font-semibold ${t.type === "income" ? "text-success" : "text-ink-900"}`}
              >
                {t.type === "income" ? "+" : "−"}
                {formatMoney(t.amount)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

const BUDGETS_SUMMARY_LIMIT = 3;

function BudgetsSummaryBlock({ budgets }: { budgets: Budget[] }) {
  const top = [...budgets]
    .sort((a, b) => b.usage_percent - a.usage_percent)
    .slice(0, BUDGETS_SUMMARY_LIMIT);
  return (
    <Card>
      <CardHeader
        title="Бюджеты этого месяца"
        action={
          <Link to="/budgets" className="text-sm font-medium text-accent hover:underline">
            Все бюджеты →
          </Link>
        }
      />
      <ul className="flex flex-col gap-4">
        {top.map((b) => (
          <li key={b.id}>
            <div className="mb-1.5 flex items-center justify-between gap-3 text-[15px]">
              <span className="truncate font-medium text-ink-900">{b.category_name}</span>
              <span className="tabular shrink-0 text-ink-500">
                {formatMoney(b.spent)} / {formatMoney(b.amount)}
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-surface-hover">
              <div
                className={`h-full rounded-full ${BUDGET_STATUS_BAR_CLASS[b.status]}`}
                style={{ width: `${Math.min(100, Math.max(0, b.usage_percent))}%` }}
              />
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

const GOALS_SUMMARY_LIMIT = 3;

function GoalsSummaryBlock({ goals }: { goals: Goal[] }) {
  const top = [...goals]
    .sort((a, b) => b.progress_percent - a.progress_percent)
    .slice(0, GOALS_SUMMARY_LIMIT);
  return (
    <Card>
      <CardHeader
        title="Финансовые цели"
        action={
          <Link to="/goals" className="text-sm font-medium text-accent hover:underline">
            Все цели →
          </Link>
        }
      />
      <ul className="flex flex-col gap-4">
        {top.map((g) => (
          <li key={g.id}>
            <div className="mb-1.5 flex items-center justify-between gap-3 text-[15px]">
              <span className="truncate font-medium text-ink-900">{g.name}</span>
              <span className="tabular shrink-0 text-ink-500">
                {formatMoney(g.saved)} / {formatMoney(g.target)}
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-surface-hover">
              <div
                className={`h-full rounded-full ${g.status === "completed" ? "bg-success" : "bg-accent"}`}
                style={{ width: `${Math.min(100, Math.max(0, g.progress_percent))}%` }}
              />
            </div>
            <p className="mt-1 text-xs text-ink-500">{g.progress_percent}%</p>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function MiniAnalyticsBlock() {
  const range = computePeriod("this_month");
  const params = range ? periodToApiParams(range) : null;
  const { data } = useQuery({
    queryKey: ["analytics", "dashboard-this-month"],
    queryFn: () => analyticsApi.get(params!.date_from, params!.date_to),
    enabled: params !== null,
  });

  return (
    <Card>
      <CardHeader
        title="Доходы и расходы (этот месяц)"
        action={
          <Link to="/analytics" className="text-sm font-medium text-accent hover:underline">
            Аналитика →
          </Link>
        }
      />
      {!data ? (
        <p className="text-[15px] text-ink-500">Загрузка…</p>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <p className="text-sm text-ink-500">Доходы</p>
              <p className="tabular mt-1 text-xl font-semibold text-success">
                {formatMoney(data.summary.income)}
              </p>
            </div>
            <div>
              <p className="text-sm text-ink-500">Расходы</p>
              <p className="tabular mt-1 text-xl font-semibold text-ink-900">
                {formatMoney(data.summary.expense)}
              </p>
            </div>
            <div>
              <p className="text-sm text-ink-500">Разница</p>
              <p
                className={`tabular mt-1 text-xl font-semibold ${data.summary.balance.minor < 0 ? "text-danger" : "text-success"}`}
              >
                {formatMoney(data.summary.balance)}
              </p>
            </div>
          </div>
          {data.timeseries.length > 1 && (
            <div className="mt-5">
              <TimeseriesChart
                points={data.timeseries}
                currency={data.currency}
                granularity={data.granularity}
              />
            </div>
          )}
        </>
      )}
    </Card>
  );
}

function TopExpensesBlock({ items }: { items: CategorySpending[] }) {
  return (
    <Card>
      <CardHeader title="Основные расходы (этот месяц)" />
      {items.length === 0 ? (
        <EmptyState>В этом месяце расходов ещё не было.</EmptyState>
      ) : (
        <ul className="divide-y divide-border">
          {items.map((c) => (
            <li key={c.category_id} className="flex items-center gap-3 py-3.5 first:pt-0 last:pb-0">
              <IconTile>
                <CategoryIcon name={c.category_name} type="expense" icon={c.icon} />
              </IconTile>
              <span className="min-w-0 flex-1 truncate text-[15px] font-medium text-ink-900">
                {c.category_name}
              </span>
              <span className="tabular text-[15px] font-semibold text-ink-900">
                {formatMoney(c.amount)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function DashboardPage() {
  const { data, isPending, isError } = useQuery({
    queryKey: ["dashboard"],
    queryFn: dashboardApi.get,
  });
  const now = new Date();
  const { data: budgets } = useQuery({
    queryKey: ["budgets", now.getFullYear(), now.getMonth() + 1],
    queryFn: () => budgetsApi.list(now.getFullYear(), now.getMonth() + 1),
  });
  const { data: goals } = useQuery({ queryKey: ["goals"], queryFn: () => goalsApi.list() });

  if (isPending) {
    return <p className="text-[15px] text-ink-500">Загрузка…</p>;
  }
  if (isError || !data) {
    return (
      <div className="rounded-2xl border border-danger/25 bg-danger-soft p-6 text-[15px] text-danger">
        Не удалось загрузить данные дашборда.
      </div>
    );
  }

  const hasDebts = data.debts.items.length > 0;
  const activeGoals = (goals ?? []).filter((g) => g.status !== "archived");
  const hasBudgets = (budgets ?? []).length > 0;
  const hasGoals = activeGoals.length > 0;

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-[28px] font-semibold tracking-tight text-ink-900">Дашборд</h1>

      <NetWorthCard
        amount={data.net_worth}
        accountCount={data.accounts.length}
        activeDebtCount={data.debts.items.length}
        budgetCount={budgets?.length ?? 0}
        activeGoalCount={activeGoals.length}
      />

      {/* Требование: если долги есть — блок долгов визуально выше счетов;
          если долгов нет — блок не рендерится вовсе, а счета занимают всю
          ширину ряда (см. AdaptiveRow). Порядок задаётся условно, а не CSS
          order, поэтому в DOM нет скрытых пустых блоков. */}
      <AdaptiveRow>
        {hasDebts && (
          <DebtsBlock summary={data.debts} />
        )}
        <AccountsBlock accounts={data.accounts} />
      </AdaptiveRow>

      <AdaptiveRow>
        {hasBudgets && <BudgetsSummaryBlock budgets={budgets!} />}
        {hasGoals && <GoalsSummaryBlock goals={activeGoals} />}
      </AdaptiveRow>

      <AdaptiveRow>
        <MiniAnalyticsBlock />
        <RecentTransactionsBlock items={data.recent_transactions} />
      </AdaptiveRow>

      <TopExpensesBlock items={data.top_expenses} />
    </div>
  );
}
