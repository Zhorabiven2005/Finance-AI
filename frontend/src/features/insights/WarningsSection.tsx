import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, EyeOff, Info, RotateCcw } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, LoadError } from "@/components/ui/Card";
import { chatErrorMessage } from "@/lib/api/assistant";
import { insightsApi, type FinancialWarning, type InsightMetric, type LargeExpenseGroup } from "@/lib/api/insights";
import { cn } from "@/lib/cn";
import { formatMoney } from "@/lib/money";

/** Финансовые предупреждения (Stage 3E). Условия и суммы — только backend;
 * здесь отображение и скрытие по стабильному ключу предупреждения. */

/** Сколько предупреждений показывать сразу: сначала важные (порядок задаёт backend). */
export const VISIBLE_WARNINGS = 3;
/** Скрытые предупреждения — удобство одного браузера, не данные: в БД не пишутся. */
export const DISMISSED_STORAGE_KEY = "finance-ai:dismissed-warnings";

const KIND: Record<FinancialWarning["kind"], string> = {
  fact: "Факт",
  estimate: "Оценка",
  observation: "Наблюдение",
};

function readDismissed(): string[] {
  try {
    const raw = window.localStorage.getItem(DISMISSED_STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function writeDismissed(keys: string[]) {
  try {
    window.localStorage.setItem(DISMISSED_STORAGE_KEY, JSON.stringify(keys));
  } catch {
    // Хранилище недоступно (приватный режим) — скрытие действует до перезагрузки.
  }
}

function metricValue(m: InsightMetric): string {
  if (m.money) return formatMoney(m.money);
  if (m.percent != null) return `${m.percent.toFixed(1).replace(".", ",")}%`;
  if (m.count != null) return String(m.count);
  return "—";
}

function WarningItem({
  warning,
  hidden,
  onToggle,
}: {
  warning: FinancialWarning;
  hidden: boolean;
  onToggle: () => void;
}) {
  const important = warning.severity === "warning";
  return (
    <li
      data-testid="warning"
      data-key={warning.key}
      className={cn(
        "flex min-w-0 flex-col gap-3 rounded-xl border border-l-4 bg-surface p-4",
        important ? "border-danger/30 border-l-danger" : "border-border border-l-warn",
        hidden && "opacity-70",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        {important && <Badge tone="danger">Важно</Badge>}
        <Badge tone={warning.kind === "estimate" ? "warn" : "neutral"}>{KIND[warning.kind]}</Badge>
        <span className="text-sm text-ink-500">
          {warning.period.label}
          {warning.currency ? ` · ${warning.currency}` : ""}
        </span>
      </div>
      <div>
        {/* Названия категорий, счетов и целей — пользовательские строки: только текст. */}
        <h3 className="flex items-start gap-2 text-[16px] font-semibold text-ink-900">
          <AlertTriangle
            className={cn("mt-0.5 h-4 w-4 shrink-0", important ? "text-danger" : "text-warn")}
            strokeWidth={1.75}
            aria-hidden
          />
          <span className="min-w-0 break-words">{warning.title}</span>
        </h3>
        <p className="mt-1 text-[15px] leading-relaxed text-ink-700">{warning.message}</p>
      </div>
      {warning.metrics.length > 0 && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
          {warning.metrics.map((m) => (
            <div key={m.label} className="min-w-0">
              <dt className="truncate text-xs text-ink-500">{m.label}</dt>
              <dd className="tabular text-[15px] font-semibold text-ink-900">{metricValue(m)}</dd>
            </div>
          ))}
        </dl>
      )}
      {warning.recommendation && (
        <p className="flex items-start gap-2 rounded-lg bg-page px-3 py-2 text-sm text-ink-700">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-ink-400" strokeWidth={1.75} aria-hidden />
          <span>{warning.recommendation}</span>
        </p>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {warning.link ? (
          <Link to={warning.link.to} className="text-sm font-medium text-accent hover:underline">
            {warning.link.label} →
          </Link>
        ) : (
          <span />
        )}
        <Button variant="secondary" size="sm" onClick={onToggle}>
          {hidden ? (
            <>
              <RotateCcw className="h-3.5 w-3.5" strokeWidth={1.75} />
              Вернуть
            </>
          ) : (
            <>
              <EyeOff className="h-3.5 w-3.5" strokeWidth={1.75} />
              Скрыть
            </>
          )}
        </Button>
      </div>
    </li>
  );
}

function plural(n: number, one: string, few: string, many: string): string {
  if (n % 10 === 1 && n % 100 !== 11) return one;
  if (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14)) return few;
  return many;
}

/** Крупные расходы одной валюты — одна компактная карточка вместо отдельной
 * на каждую операцию. Число и сумма — из сводки backend; операции
 * раскрываются списком и скрываются по своим ключам, как раньше. */
function LargeExpenseGroupItem({
  group,
  items,
  onToggle,
  onHideAll,
}: {
  group: LargeExpenseGroup;
  items: FinancialWarning[];
  onToggle: (key: string) => void;
  onHideAll: () => void;
}) {
  const [open, setOpen] = useState(false);
  const hiddenCount = group.count - items.length;
  const recommendation = items.find((w) => w.recommendation)?.recommendation;
  return (
    <li
      data-testid="warning-group"
      data-currency={group.currency}
      className="flex min-w-0 flex-col gap-3 rounded-xl border border-l-4 border-border border-l-warn bg-surface p-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="neutral">{KIND.observation}</Badge>
        <span className="text-sm text-ink-500">
          {group.period.label} · {group.currency}
        </span>
      </div>
      <div>
        <h3 className="flex items-start gap-2 text-[16px] font-semibold text-ink-900">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warn" strokeWidth={1.75} aria-hidden />
          <span className="min-w-0 break-words">
            Крупные расходы: {group.count} {plural(group.count, "операция", "операции", "операций")} на{" "}
            {formatMoney(group.total)}
          </span>
        </h3>
        <p className="mt-1 text-[15px] leading-relaxed text-ink-700">
          Эти операции заметно больше ваших обычных трат. Крупная операция не обязательно лишний расход: её назначение
          может быть неизвестно приложению — например, это может быть перевод на ваш счёт или договор в другом банке.
        </p>
        {hiddenCount > 0 && (
          <p className="mt-1 text-sm text-ink-500">
            Из них скрыто: {hiddenCount} — они в списке скрытых ниже.
          </p>
        )}
      </div>
      {recommendation && (
        <p className="flex items-start gap-2 rounded-lg bg-page px-3 py-2 text-sm text-ink-700">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-ink-400" strokeWidth={1.75} aria-hidden />
          <span>{recommendation}</span>
        </p>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button variant="secondary" size="sm" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} strokeWidth={1.75} />
          {open ? "Свернуть операции" : `Показать операции (${items.length})`}
        </Button>
        <Button variant="secondary" size="sm" onClick={onHideAll}>
          <EyeOff className="h-3.5 w-3.5" strokeWidth={1.75} />
          Скрыть все
        </Button>
      </div>
      {open && (
        <ul data-testid="warning-group-items" className="flex flex-col">
          {items.map((w) => (
            <li
              key={w.key}
              data-testid="warning-group-item"
              data-key={w.key}
              className="flex flex-col gap-1 border-t border-border py-3 first:border-t-0 first:pt-0 last:pb-0"
            >
              <p className="text-[15px] font-medium text-ink-900">{w.title}</p>
              <p className="text-sm leading-relaxed text-ink-700">{w.message}</p>
              <div className="flex flex-wrap items-center justify-between gap-2">
                {w.link ? (
                  <Link to={w.link.to} className="text-sm font-medium text-accent hover:underline">
                    {w.link.label} →
                  </Link>
                ) : (
                  <span />
                )}
                <Button variant="secondary" size="sm" onClick={() => onToggle(w.key)}>
                  <EyeOff className="h-3.5 w-3.5" strokeWidth={1.75} />
                  Скрыть
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

type Entry =
  | { kind: "warning"; key: string; warning: FinancialWarning }
  | { kind: "group"; key: string; group: LargeExpenseGroup; items: FinancialWarning[] };

/** Порядок — как у backend; предупреждения о крупных расходах одной валюты
 * сворачиваются в одну сводку на месте первого из них. */
function buildEntries(active: FinancialWarning[], groups: LargeExpenseGroup[]): Entry[] {
  const groupOf = new Map<string, LargeExpenseGroup>();
  for (const g of groups) for (const k of g.keys) groupOf.set(k, g);
  const entries: Entry[] = [];
  const placed = new Set<LargeExpenseGroup>();
  for (const w of active) {
    const g = groupOf.get(w.key);
    if (!g) {
      entries.push({ kind: "warning", key: w.key, warning: w });
    } else if (!placed.has(g)) {
      placed.add(g);
      entries.push({
        kind: "group",
        key: `group:large_expense:${g.currency}`,
        group: g,
        items: active.filter((x) => groupOf.get(x.key) === g),
      });
    }
  }
  return entries;
}

export function WarningsSection() {
  const query = useQuery({ queryKey: ["insights-warnings"], queryFn: insightsApi.warnings });
  const [dismissed, setDismissed] = useState<string[]>(readDismissed);
  const [showAll, setShowAll] = useState(false);
  const [showHidden, setShowHidden] = useState(false);

  const all = query.data?.warnings ?? [];
  const active = all.filter((w) => !dismissed.includes(w.key));
  const hidden = all.filter((w) => dismissed.includes(w.key));
  const entries = buildEntries(active, query.data?.large_expense_groups ?? []);
  const visible = showAll ? entries : entries.slice(0, VISIBLE_WARNINGS);

  const save = (next: string[]) => {
    setDismissed(next);
    writeDismissed(next);
  };
  // Храним только ключи актуальных предупреждений: прошедшие события не копятся.
  const current = () => new Set(all.map((w) => w.key));
  const toggle = (key: string) =>
    save(dismissed.includes(key) ? dismissed.filter((k) => k !== key) : [...dismissed.filter((k) => current().has(k)), key]);
  const hideAll = (keys: string[]) =>
    save([...new Set([...dismissed.filter((k) => current().has(k)), ...keys])]);

  return (
    <Card>
      <div className="mb-5 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold tracking-tight text-ink-900">Финансовые предупреждения</h2>
        {query.data && entries.length > 0 && <span className="text-sm text-ink-500">Актуальных: {entries.length}</span>}
      </div>
      {query.isPending ? (
        <p className="text-[15px] text-ink-500">Проверяю данные…</p>
      ) : query.isError ? (
        <LoadError onRetry={() => query.refetch()} retrying={query.isFetching}>
          Не удалось проверить предупреждения: {chatErrorMessage(query.error)}
        </LoadError>
      ) : (
        <>
          {active.length === 0 ? (
            <p data-testid="warnings-empty" className="py-4 text-[15px] text-ink-500">
              {hidden.length > 0 ? "Актуальных предупреждений нет — остальные вы скрыли." : "Сейчас предупреждений нет."}
            </p>
          ) : (
            <ul className="grid grid-cols-1 gap-3">
              {visible.map((e) =>
                e.kind === "group" ? (
                  <LargeExpenseGroupItem
                    key={e.key}
                    group={e.group}
                    items={e.items}
                    onToggle={toggle}
                    onHideAll={() => hideAll(e.items.map((w) => w.key))}
                  />
                ) : (
                  <WarningItem key={e.key} warning={e.warning} hidden={false} onToggle={() => toggle(e.key)} />
                ),
              )}
            </ul>
          )}
          {entries.length > VISIBLE_WARNINGS && (
            <div className="mt-4 flex justify-center">
              <Button variant="secondary" size="sm" onClick={() => setShowAll((v) => !v)}>
                {showAll ? "Свернуть" : `Показать все (${entries.length})`}
              </Button>
            </div>
          )}
          {hidden.length > 0 && (
            <div className="mt-4">
              <button
                type="button"
                className="text-sm text-ink-500 underline-offset-2 hover:underline"
                aria-expanded={showHidden}
                onClick={() => setShowHidden((v) => !v)}
              >
                {showHidden ? "Не показывать скрытые" : `Скрытые предупреждения (${hidden.length})`}
              </button>
              {showHidden && (
                <ul className="mt-3 grid grid-cols-1 gap-3">
                  {hidden.map((w) => (
                    <WarningItem key={w.key} warning={w} hidden onToggle={() => toggle(w.key)} />
                  ))}
                </ul>
              )}
            </div>
          )}
          {query.data && query.data.limitations.length > 0 && (
            <details className="mt-4 text-sm text-ink-500">
              <summary className="cursor-pointer select-none">
                Что не удалось проверить ({query.data.limitations.length})
              </summary>
              <ul className="mt-2 flex flex-col gap-1 pl-5">
                {query.data.limitations.map((l) => (
                  <li key={l} className="list-disc">
                    {l}
                  </li>
                ))}
              </ul>
            </details>
          )}
          <p className="mt-4 text-xs text-ink-400">
            Предупреждения считает приложение по вашим данным. «Оценка» — расчёт по темпу трат, а не прогноз; крупный
            расход или рост категории не означает ошибку.
          </p>
        </>
      )}
    </Card>
  );
}
