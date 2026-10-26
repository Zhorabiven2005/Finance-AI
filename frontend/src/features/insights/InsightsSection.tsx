import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, LoadError } from "@/components/ui/Card";
import { assistantApi, chatErrorMessage } from "@/lib/api/assistant";
import {
  insightsApi,
  type Insight,
  type InsightItem,
  type InsightMetric,
  type InsightPeriodKey,
  type InsightType,
} from "@/lib/api/insights";
import { cn } from "@/lib/cn";
import { formatMoney } from "@/lib/money";

import { ComparisonBlock } from "./ComparisonBlock";
import { ExplanationBlock } from "./ExplanationBlock";

/** Сколько выводов показывать сразу — остальные по кнопке, чтобы не
 * перегружать дашборд. Порядок задаёт backend: сначала важное. */
export const VISIBLE_INSIGHTS = 4;

const PERIODS: [InsightPeriodKey, string][] = [
  ["current_month", "Этот месяц"],
  ["previous_month", "Прошлый месяц"],
  ["last_3_months", "3 месяца"],
];

const TYPE_LABEL: Record<InsightType, string> = {
  cash_flow: "Доходы и расходы",
  spending_structure: "Структура расходов",
  large_expenses: "Крупные расходы",
  recurring_expenses: "Регулярные платежи",
  budgets: "Бюджеты",
  goals: "Цели",
  data_quality: "Качество данных",
};

const SEVERITY: Record<Insight["severity"], { label: string; tone: "danger" | "warn" | "neutral" }> = {
  warning: { label: "Важно", tone: "danger" },
  attention: { label: "Обратите внимание", tone: "warn" },
  info: { label: "Для сведения", tone: "neutral" },
};

const CONFIDENCE_LABEL: Record<Insight["confidence"], string> = {
  high: "высокая",
  medium: "средняя",
  low: "низкая",
};

const percent = (value: number) => `${value.toFixed(1).replace(".", ",")}%`;
const isoDate = (value: string) => value.split("-").reverse().join(".");

function metricValue(m: InsightMetric): string {
  if (m.money) return formatMoney(m.money);
  if (m.percent != null) return percent(m.percent);
  if (m.count != null) return String(m.count);
  return "—";
}

function ItemRow({ item }: { item: InsightItem }) {
  return (
    <li className="flex flex-col gap-0.5 border-t border-border pt-2 first:border-t-0 first:pt-0">
      <div className="flex items-baseline justify-between gap-3 text-[15px]">
        {/* Названия — пользовательские строки: выводятся как текст. */}
        <span className="min-w-0 truncate text-ink-900">{item.label}</span>
        <span className="tabular shrink-0 text-ink-700">
          {item.money ? formatMoney(item.money) : null}
          {item.percent != null && <span className="ml-2 text-ink-500">{percent(item.percent)}</span>}
        </span>
      </div>
      {(item.note || item.date) && (
        <p className="text-sm text-ink-500">
          {item.date && <span>{isoDate(item.date)}</span>}
          {item.date && item.note && " · "}
          {item.note}
        </p>
      )}
    </li>
  );
}

function InsightCard({ insight, period, canExplain }: { insight: Insight; period: InsightPeriodKey; canExplain: boolean }) {
  const severity = SEVERITY[insight.severity];
  return (
    <li
      data-testid="insight"
      data-type={insight.type}
      className="flex min-w-0 flex-col gap-3 rounded-xl border border-border bg-surface p-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={severity.tone}>{severity.label}</Badge>
        <span className="text-xs font-medium uppercase tracking-wide text-ink-400">{TYPE_LABEL[insight.type]}</span>
      </div>
      <div>
        <h3 className="text-[17px] font-semibold text-ink-900">{insight.title}</h3>
        <p className="text-sm text-ink-500">
          {insight.period.label}
          {insight.currency ? ` · ${insight.currency}` : ""}
        </p>
      </div>
      {insight.metrics.length > 0 && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
          {insight.metrics.map((m) => (
            <div key={m.label} className="min-w-0">
              <dt className="truncate text-xs text-ink-500">{m.label}</dt>
              <dd className="tabular text-[15px] font-semibold text-ink-900">{metricValue(m)}</dd>
            </div>
          ))}
        </dl>
      )}
      {insight.items.length > 0 && (
        <ul className="flex flex-col gap-2">
          {insight.items.map((item, i) => (
            <ItemRow key={`${item.label}-${i}`} item={item} />
          ))}
        </ul>
      )}
      <p className="text-[15px] leading-relaxed text-ink-700">{insight.summary}</p>
      <div className="text-sm text-ink-500">
        <p>Уверенность: {CONFIDENCE_LABEL[insight.confidence]}</p>
        {insight.limitations.length > 0 && (
          <ul className="mt-1 list-disc pl-5">
            {insight.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        )}
      </div>
      <div className="mt-auto flex flex-wrap items-center justify-between gap-3">
        {insight.link ? (
          <Link to={insight.link.to} className="text-sm font-medium text-accent hover:underline">
            {insight.link.label} →
          </Link>
        ) : (
          <span />
        )}
        {canExplain && <ExplanationBlock key={`${insight.id}-${period}`} insightId={insight.id} period={period} />}
      </div>
    </li>
  );
}

export function InsightsSection() {
  const [period, setPeriod] = useState<InsightPeriodKey>("current_month");
  const [showAll, setShowAll] = useState(false);
  const query = useQuery({ queryKey: ["insights", period], queryFn: () => insightsApi.get(period) });
  const assistant = useQuery({ queryKey: ["assistant-status"], queryFn: assistantApi.status, retry: false });
  const canExplain = assistant.data?.ready === true;

  const insights = query.data?.insights ?? [];
  const visible = showAll ? insights : insights.slice(0, VISIBLE_INSIGHTS);

  return (
    <Card>
      {/* Не CardHeader: переключатель периода должен переноситься под
          заголовок на узком экране, а не выходить за край карточки. */}
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold tracking-tight text-ink-900">Финансовые инсайты</h2>
        <div
          className="flex gap-1 rounded-lg border border-border bg-surface p-1 text-sm"
          role="tablist"
          aria-label="Период инсайтов"
        >
          {PERIODS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={period === key}
              onClick={() => {
                setPeriod(key);
                setShowAll(false);
              }}
              className={cn(
                "rounded-md px-3 py-1.5 font-medium",
                period === key ? "bg-accent-soft text-accent" : "text-ink-500 hover:text-ink-900",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {query.isPending ? (
        <p className="text-[15px] text-ink-500">Считаю выводы…</p>
      ) : query.isError ? (
        <LoadError onRetry={() => query.refetch()} retrying={query.isFetching}>
          Не удалось посчитать инсайты: {chatErrorMessage(query.error)}
        </LoadError>
      ) : (
        <>
          {query.data?.comparison && (
            <ComparisonBlock comparison={query.data.comparison} period={period} canExplain={canExplain} />
          )}
          {insights.length === 0 ? (
            <p className="py-6 text-center text-[15px] text-ink-500">
              Пока недостаточно данных для выводов за этот период.
            </p>
          ) : (
            <ul className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {visible.map((i) => (
                <InsightCard key={i.id} insight={i} period={period} canExplain={canExplain} />
              ))}
            </ul>
          )}
          {insights.length > VISIBLE_INSIGHTS && (
            <div className="mt-4 flex justify-center">
              <Button variant="secondary" size="sm" onClick={() => setShowAll((v) => !v)}>
                {showAll ? "Свернуть" : `Показать все (${insights.length})`}
              </Button>
            </div>
          )}
          {query.data && query.data.unavailable.length > 0 && (
            <details className="mt-4 text-sm text-ink-500">
              <summary className="cursor-pointer select-none">
                Почему нет других выводов ({query.data.unavailable.length})
              </summary>
              <ul className="mt-2 flex flex-col gap-1 pl-5">
                {query.data.unavailable.map((u, i) => (
                  <li key={`${u.type}-${u.currency}-${i}`} className="list-disc">
                    {TYPE_LABEL[u.type]}
                    {u.currency ? ` (${u.currency})` : ""}: {u.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
          <p className="mt-4 text-xs text-ink-400">
            Все суммы и проценты посчитаны приложением по вашим операциям. Это наблюдения по истории, а не прогноз и
            не финансовая консультация.
            {!canExplain && !assistant.isPending && " Объяснения локальной модели сейчас недоступны — выводы выше от этого не зависят."}
          </p>
        </>
      )}
    </Card>
  );
}
