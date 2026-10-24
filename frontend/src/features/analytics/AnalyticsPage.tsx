import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useState } from "react";
import { ArrowDown, ArrowUp, Receipt } from "lucide-react";
import { Link } from "react-router-dom";

import { PeriodPicker } from "@/components/PeriodPicker";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { Modal } from "@/components/ui/Modal";
import { analyticsApi } from "@/lib/api/analytics";
import { errorMessage } from "@/lib/api/client";
import { transactionsApi } from "@/lib/api/transactions";
import { formatMoney } from "@/lib/money";
import { computePeriod, periodToApiParams, type PeriodPreset } from "@/lib/period";

import { CategoryBreakdownList } from "./CategoryBreakdownList";
import { TimeseriesChart } from "./TimeseriesChart";
import { TopExpensesList } from "./TopExpensesList";
import { TransactionFormModal } from "../transactions/TransactionFormModal";

const ANALYTICS_PRESETS: PeriodPreset[] = ["today", "7d", "this_month", "last_month", "3m", "custom"];

function ComparisonBadge({
  percent,
  goodWhenPositive,
}: {
  percent: number | null;
  goodWhenPositive: boolean;
}) {
  if (percent === null) return <span className="text-sm text-ink-400">нет данных за прошлый период</span>;
  if (percent === 0) return <span className="text-sm font-medium text-ink-500">без изменений</span>;

  const isPositive = percent > 0;
  const isGood = goodWhenPositive ? isPositive : !isPositive;
  const Icon = isPositive ? ArrowUp : ArrowDown;
  return (
    <span
      className={`inline-flex items-center gap-1 text-sm font-medium ${isGood ? "text-success" : "text-danger"}`}
    >
      <Icon className="h-3.5 w-3.5" strokeWidth={2.5} />
      {Math.abs(percent).toFixed(1)}% к прошлому периоду
    </span>
  );
}

function SummaryCard({
  label,
  value,
  tone,
  comparison,
}: {
  label: string;
  value: string;
  tone: "positive" | "negative" | "neutral";
  comparison?: ReactNode;
}) {
  const toneClass =
    tone === "positive" ? "text-success" : tone === "negative" ? "text-danger" : "text-ink-900";
  return (
    <Card>
      <p className="text-sm font-medium text-ink-500">{label}</p>
      <p className={`tabular mt-2 text-3xl font-semibold tracking-tight ${toneClass}`}>{value}</p>
      {comparison && <div className="mt-2">{comparison}</div>}
    </Card>
  );
}

export function AnalyticsPage() {
  const queryClient = useQueryClient();
  const [preset, setPreset] = useState<PeriodPreset>("this_month");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [openingTxId, setOpeningTxId] = useState<number | null>(null);

  const period = computePeriod(preset, { from: customFrom, to: customTo }) ?? computePeriod("this_month")!;
  const { date_from, date_to } = periodToApiParams(period);

  const { data, isPending, isError } = useQuery({
    queryKey: ["analytics", date_from, date_to],
    queryFn: () => analyticsApi.get(date_from, date_to),
  });

  const {
    data: openingTx,
    isError: openingFailed,
    error: openingError,
  } = useQuery({
    queryKey: ["transaction", openingTxId],
    queryFn: () => transactionsApi.get(openingTxId as number),
    enabled: openingTxId !== null,
    retry: false,
  });
  const closeOpening = () => setOpeningTxId(null);
  // Изменение операции из аналитики меняет и балансы, и бюджеты, и Dashboard.
  const invalidateAfterEdit = () => {
    for (const key of ["transactions", "transaction", "accounts", "dashboard", "analytics", "budgets"]) {
      queryClient.invalidateQueries({ queryKey: [key] });
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-[28px] font-semibold tracking-tight text-ink-900">Аналитика</h1>
        <PeriodPicker
          preset={preset}
          onPresetChange={setPreset}
          customFrom={customFrom}
          customTo={customTo}
          onCustomChange={(from, to) => {
            setCustomFrom(from);
            setCustomTo(to);
          }}
          presets={ANALYTICS_PRESETS}
        />
      </div>

      {isPending ? (
        <p className="text-[15px] text-ink-500">Загрузка…</p>
      ) : isError || !data ? (
        <div className="rounded-2xl border border-danger/25 bg-danger-soft p-6 text-[15px] text-danger">
          Не удалось загрузить аналитику.
        </div>
      ) : (
        <>
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            <SummaryCard
              label="Доходы"
              value={`+${formatMoney(data.summary.income)}`}
              tone="positive"
              comparison={
                <ComparisonBadge percent={data.comparison.income_change_percent} goodWhenPositive />
              }
            />
            <SummaryCard
              label="Расходы"
              value={`−${formatMoney(data.summary.expense)}`}
              tone="negative"
              comparison={
                <ComparisonBadge
                  percent={data.comparison.expense_change_percent}
                  goodWhenPositive={false}
                />
              }
            />
            <SummaryCard
              label="Итог"
              value={formatMoney(data.summary.balance, { signDisplay: "always" })}
              tone={data.summary.balance.minor >= 0 ? "positive" : "negative"}
            />
            <SummaryCard
              label="Операций"
              value={String(data.summary.transaction_count)}
              tone="neutral"
            />
          </div>

          <Card>
            <CardHeader title="Динамика доходов и расходов" />
            <TimeseriesChart
              points={data.timeseries}
              currency={data.currency}
              granularity={data.granularity}
            />
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader title="Расходы по категориям" />
              <CategoryBreakdownList items={data.category_breakdown} />
            </Card>
            <Card>
              <CardHeader
                title="Крупнейшие расходы"
                action={<Receipt className="h-4 w-4 text-ink-400" strokeWidth={1.75} />}
              />
              <TopExpensesList items={data.top_expenses} onSelect={setOpeningTxId} />
            </Card>
          </div>
        </>
      )}

      {openingTxId !== null && openingFailed && (
        <ConfirmModal title="Не удалось открыть операцию" onClose={closeOpening}>
          {errorMessage(openingError)}
        </ConfirmModal>
      )}
      {openingTxId !== null && openingTx?.debt_id ? (
        // Платёж по долгу — часть долга: правится и удаляется только в
        // карточке долга, иначе долг и журнал разойдутся (backend всё равно
        // отклонит такое изменение).
        <Modal title="Платёж по долгу" onClose={closeOpening}>
          <div className="flex flex-col gap-6">
            <p className="text-[15px] text-ink-500">
              Расход {formatMoney(openingTx.amount)}
              {openingTx.debt_name && <> — платёж по долгу «{openingTx.debt_name}»</>}. Изменить или удалить его
              можно только в карточке долга.{" "}
              <Link to={`/transactions?tx=${openingTx.id}`} className="font-medium text-accent hover:underline">
                Показать в журнале
              </Link>
            </p>
            <div className="flex flex-wrap justify-end gap-3">
              <Button type="button" variant="secondary" onClick={closeOpening} autoFocus>
                Понятно
              </Button>
              <Link
                to={`/debts/${openingTx.debt_id}`}
                className="inline-flex h-11 items-center rounded-lg bg-accent px-5 text-[15px] font-medium text-white shadow-sm hover:bg-accent-hover"
              >
                Открыть долг
              </Link>
            </div>
          </div>
        </Modal>
      ) : (
        openingTxId !== null &&
        openingTx && (
          <TransactionFormModal
            type={openingTx.type}
            transaction={openingTx}
            onClose={closeOpening}
            onSaved={() => {
              closeOpening();
              invalidateAfterEdit();
            }}
          />
        )
      )}
    </div>
  );
}
