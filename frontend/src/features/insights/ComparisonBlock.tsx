import { AlertTriangle, ArrowDownRight, ArrowUpRight, ChevronDown, Minus } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import type { Change, CurrencyComparison, InsightPeriodKey, PeriodComparison } from "@/lib/api/insights";
import { cn } from "@/lib/cn";
import { formatMoney, type MoneyAmount } from "@/lib/money";

import { ExplanationBlock } from "./ExplanationBlock";

/** Сравнение с прошлым периодом (Stage 3D). Все суммы, разницы и проценты
 * посчитаны backend; здесь только отображение. Рост расходов и рост доходов
 * различаются цветом и словами, а не только стрелкой. */

/** Для расходов рост — «внимание», для доходов и разницы — «хорошо». */
type Kind = "expense" | "income";

const CONFIDENCE: Record<CurrencyComparison["confidence"], { label: string; tone: "ok" | "warn" | "danger" }> = {
  high: { label: "Сравнение надёжное", tone: "ok" },
  medium: { label: "Сравнение приблизительное", tone: "warn" },
  low: { label: "Сравнение ненадёжное", tone: "danger" },
};

const PERCENT_NULL: Record<NonNullable<Change["percent_null_reason"]>, string> = {
  zero_base: "раньше было 0, процент не считается",
  insufficient_history: "мало истории, процент не считается",
};

const pct = (value: number) => `${value > 0 ? "+" : ""}${value.toFixed(1).replace(".", ",")}%`;

function signedMoney(m: MoneyAmount): string {
  if (m.minor > 0) return `+${formatMoney(m)}`;
  if (m.minor < 0) return `−${formatMoney({ ...m, minor: -m.minor })}`;
  return formatMoney(m);
}

function ChangeLine({ change, kind, compact = false }: { change: Change; kind: Kind; compact?: boolean }) {
  const d = change.delta.minor;
  const good = kind === "expense" ? d < 0 : d > 0;
  // Без истории за прошлый период разница — не вывод, а артефакт: без цвета.
  const neutral = d === 0 || change.percent_null_reason === "insufficient_history";
  const Icon = d > 0 ? ArrowUpRight : d < 0 ? ArrowDownRight : Minus;
  const word = d > 0 ? "больше" : d < 0 ? "меньше" : "без изменений";
  return (
    <p
      data-testid="change"
      data-direction={d > 0 ? "up" : d < 0 ? "down" : "same"}
      data-neutral={neutral}
      className={cn(
        "flex flex-wrap items-center gap-x-1.5 text-sm",
        neutral ? "text-ink-500" : good ? "text-success" : "text-warn",
      )}
    >
      <Icon className="h-4 w-4 shrink-0" strokeWidth={1.75} aria-hidden />
      <span className="tabular">{d === 0 ? word : `${signedMoney(change.delta)} · ${word}`}</span>
      {change.percent != null ? (
        <span className="tabular">({pct(change.percent)})</span>
      ) : (
        d !== 0 && !compact && change.percent_null_reason && (
          <span className="text-ink-400">({PERCENT_NULL[change.percent_null_reason]})</span>
        )
      )}
    </p>
  );
}

function StatTile({ label, change, kind }: { label: string; change: Change; kind: Kind }) {
  return (
    <div className="min-w-0 rounded-xl bg-page px-4 py-3">
      <p className="text-sm text-ink-500">{label}</p>
      <p className="tabular mt-1 text-xl font-semibold text-ink-900">{formatMoney(change.current)}</p>
      <p className="tabular text-xs text-ink-400">было {formatMoney(change.previous)}</p>
      <div className="mt-1">
        <ChangeLine change={change} kind={kind} />
      </div>
    </div>
  );
}

function DetailRow({ label, change, kind }: { label: string; change: Change; kind: Kind }) {
  return (
    <li className="flex flex-col gap-0.5 border-t border-border py-2 first:border-t-0 sm:flex-row sm:items-baseline sm:justify-between sm:gap-3">
      {/* Названия категорий — пользовательские строки: выводятся как текст. */}
      <span className="min-w-0 truncate text-[15px] text-ink-900">{label}</span>
      <span className="flex flex-wrap items-baseline gap-x-3 sm:justify-end">
        <span className="tabular text-sm text-ink-500">
          {formatMoney(change.current)} <span className="text-ink-400">/ было {formatMoney(change.previous)}</span>
        </span>
        <ChangeLine change={change} kind={kind} compact />
      </span>
    </li>
  );
}

function CurrencyBlock({
  item,
  comparison,
  period,
  canExplain,
}: {
  item: CurrencyComparison;
  comparison: PeriodComparison;
  period: InsightPeriodKey;
  canExplain: boolean;
}) {
  const [open, setOpen] = useState(false);
  const confidence = CONFIDENCE[item.confidence];
  const hasDebt = item.debt_repayments.current.minor !== 0 || item.debt_repayments.previous.minor !== 0;
  const share = item.other_share;
  return (
    <div data-testid="comparison-currency" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={confidence.tone}>{confidence.label}</Badge>
        {comparison.by_currency.length > 1 && <span className="text-sm text-ink-500">{item.currency}</span>}
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatTile label="Доходы" change={item.income} kind="income" />
        {/* Основной показатель — расходы на жизнь: без погашений долгов, чтобы
            покупки по кредитке не учитывались второй раз. */}
        <StatTile label="Расходы на жизнь" change={item.expense_without_debt_repayments} kind="expense" />
        <StatTile label="Доходы минус все расходы" change={item.net} kind="income" />
      </div>

      <p className="text-[15px] leading-relaxed text-ink-700">{item.summary}</p>

      {item.warnings.length > 0 && (
        <ul data-testid="comparison-warnings" className="flex flex-col gap-2 rounded-xl border border-warn/30 bg-warn-soft/40 px-4 py-3">
          {item.warnings.map((w) => (
            <li key={w} className="flex items-start gap-2 text-sm text-ink-700">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warn" strokeWidth={1.75} />
              <span>{w}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button variant="secondary" size="sm" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} strokeWidth={1.75} />
          {open ? "Скрыть подробности" : "Подробнее"}
        </Button>
        {canExplain && (
          <ExplanationBlock key={`comparison-${item.currency}-${period}`} insightId={`comparison:${item.currency}`} period={period} />
        )}
      </div>

      {open && (
        <div data-testid="comparison-details" className="flex flex-col gap-5">
          {item.categories.length > 0 && (
            <section>
              <h4 className="mb-1 text-sm font-semibold text-ink-900">Расходы по категориям</h4>
              <ul>
                {item.categories.map((c) => (
                  <DetailRow key={c.category_id} label={c.label} change={c} kind="expense" />
                ))}
              </ul>
              {item.categories_truncated && <p className="text-xs text-ink-400">Показаны категории с наибольшими изменениями.</p>}
            </section>
          )}

          <section>
            <h4 className="mb-1 text-sm font-semibold text-ink-900">Из чего состоят расходы</h4>
            <ul>
              <DetailRow label="Расходы на жизнь" change={item.expense_without_debt_repayments} kind="expense" />
              {hasDebt && (
                <>
                  <DetailRow label="Погашения долгов (не входят в расходы на жизнь)" change={item.debt_repayments} kind="expense" />
                  <DetailRow label="Все расходы вместе с погашениями" change={item.expense} kind="expense" />
                </>
              )}
              {item.large_expenses && (
                <DetailRow
                  label={`Крупные расходы (от ${formatMoney(item.large_expenses.threshold)}): ${item.large_expenses.current_count} шт., было ${item.large_expenses.previous_count}`}
                  change={item.large_expenses.total}
                  kind="expense"
                />
              )}
            </ul>
            {item.large_expenses_null_reason && <p className="mt-1 text-sm text-ink-500">{item.large_expenses_null_reason}</p>}
          </section>

          <section className="flex flex-col gap-1 text-sm text-ink-500">
            <h4 className="text-sm font-semibold text-ink-900">Что не входит в доходы и расходы</h4>
            <p>
              Переводы между своими счетами: сейчас {item.transfers_excluded.current_count} на{" "}
              {formatMoney(item.transfers_excluded.current_total)}, было {item.transfers_excluded.previous_count} на{" "}
              {formatMoney(item.transfers_excluded.previous_total)}.
            </p>
            {((item.transfers_excluded.marked_current_count ?? 0) > 0 || (item.transfers_excluded.marked_previous_count ?? 0) > 0) && (
              <p data-testid="marked-transfers">
                Отмечены вами как переводы: сейчас {item.transfers_excluded.marked_current_count ?? 0}
                {item.transfers_excluded.marked_current_total ? ` на ${formatMoney(item.transfers_excluded.marked_current_total)}` : ""},
                было {item.transfers_excluded.marked_previous_count ?? 0}
                {item.transfers_excluded.marked_previous_total ? ` на ${formatMoney(item.transfers_excluded.marked_previous_total)}` : ""}.
              </p>
            )}
            {item.possible_internal_pairs.count > 0 && (
              <p>
                Возможные переводы, записанные как доход и расход: {item.possible_internal_pairs.count} на{" "}
                {formatMoney(item.possible_internal_pairs.total)} — они учтены в суммах выше.
              </p>
            )}
            {(share.current != null || share.previous != null) && (
              <p>
                Доля «Прочих расходов»: {share.current != null ? `${share.current.toFixed(1).replace(".", ",")}%` : "—"} сейчас,{" "}
                {share.previous != null ? `${share.previous.toFixed(1).replace(".", ",")}%` : "—"} раньше
                {share.delta_points != null && share.delta_points !== 0 && (
                  <> ({share.delta_points > 0 ? "+" : ""}{share.delta_points.toFixed(1).replace(".", ",")} п. п.)</>
                )}
                .
              </p>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

export function ComparisonBlock({
  comparison,
  period,
  canExplain,
}: {
  comparison: PeriodComparison;
  period: InsightPeriodKey;
  canExplain: boolean;
}) {
  return (
    <section data-testid="comparison" className="mb-6 rounded-xl border border-border p-4 sm:p-5">
      <h3 className="text-[17px] font-semibold text-ink-900">Сравнение с прошлым периодом</h3>
      <p className="mt-0.5 text-sm text-ink-500">
        <span className="font-medium text-ink-700">{comparison.current.label}</span> против{" "}
        <span className="font-medium text-ink-700">{comparison.previous.label}</span>
      </p>
      <p className="mt-1 text-sm text-ink-400">{comparison.note}</p>
      <div className="mt-4 flex flex-col gap-6">
        {comparison.unavailable_reason ? (
          <p className="text-[15px] text-ink-500">{comparison.unavailable_reason}</p>
        ) : (
          comparison.by_currency.map((item) => (
            <CurrencyBlock key={item.currency} item={item} comparison={comparison} period={period} canExplain={canExplain} />
          ))
        )}
      </div>
    </section>
  );
}
