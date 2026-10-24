import { useMutation, useQuery } from "@tanstack/react-query";
import { HandCoins } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { Card, EmptyState, LoadError } from "@/components/ui/Card";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { Select } from "@/components/ui/Field";
import { errorMessage } from "@/lib/api/client";
import { debtsApi, type Debt } from "@/lib/api/debts";
import { cn } from "@/lib/cn";
import { sortDebts, type DebtSort } from "@/lib/debtDue";
import { formatMoney } from "@/lib/money";

import { DebtFormModal } from "./DebtFormModal";
import { DebtPaymentModal } from "./DebtPaymentModal";
import { DebtProgress, DueBadge, formatDate, useInvalidateDebts } from "./debtShared";

const SORT_OPTIONS: { value: DebtSort; label: string }[] = [
  { value: "urgency", label: "Сначала просроченные" },
  { value: "due", label: "Ближайший срок" },
  { value: "remaining", label: "Наибольший остаток" },
];

export function DebtsPage() {
  const invalidate = useInvalidateDebts();
  const [formOpen, setFormOpen] = useState(false);
  const [payingDebt, setPayingDebt] = useState<Debt | null>(null);
  const [deleting, setDeleting] = useState<Debt | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [tab, setTab] = useState<"active" | "paid">("active");
  const [sort, setSort] = useState<DebtSort>("urgency");

  const {
    data: debts,
    isPending,
    isError,
    isFetching,
    refetch,
  } = useQuery({ queryKey: ["debts"], queryFn: debtsApi.list });

  const remove = useMutation({
    mutationFn: (id: number) => debtsApi.remove(id),
    onSuccess: () => {
      setDeleting(null);
      invalidate();
    },
    onError: (err) => setDeleteError(errorMessage(err, "Не удалось удалить долг")),
  });

  const active = (debts ?? []).filter((d) => d.status !== "paid");
  const paid = (debts ?? []).filter((d) => d.status === "paid");
  const shown = sortDebts(tab === "active" ? active : paid, sort);
  const overdue = active.filter((d) => d.due_state === "overdue").length;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-[28px] font-semibold tracking-tight text-ink-900">Долги</h1>
        <Button onClick={() => setFormOpen(true)}>+ Новый долг</Button>
      </div>

      <Card>
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
            <div className="flex gap-1 rounded-lg border border-border bg-surface p-1 text-sm" role="tablist">
              {(
                [
                  ["active", `Активные (${active.length})`],
                  ["paid", `Погашенные (${paid.length})`],
                ] as const
              ).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={tab === key}
                  onClick={() => setTab(key)}
                  className={cn(
                    "rounded-md px-3 py-1.5 font-medium",
                    tab === key ? "bg-accent-soft text-accent" : "text-ink-500 hover:text-ink-900",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
            <Select
              aria-label="Сортировка долгов"
              value={sort}
              onChange={(e) => setSort(e.target.value as DebtSort)}
              className="w-56"
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
        </div>
        {tab === "active" && overdue > 0 && (
          <p className="mb-4 rounded-lg bg-danger-soft px-4 py-2.5 text-sm text-danger">
            Просрочено долгов: {overdue}
          </p>
        )}
        {isPending ? (
          <p className="text-[15px] text-ink-500">Загрузка…</p>
        ) : isError ? (
          <LoadError onRetry={() => refetch()} retrying={isFetching} />
        ) : shown.length === 0 ? (
          <EmptyState>{tab === "active" ? "Активных долгов нет." : "Погашенных долгов пока нет."}</EmptyState>
        ) : (
          <ul className="divide-y divide-border">
            {shown.map((d) => (
              <li key={d.id} data-testid="debt-row" className="flex flex-wrap items-center gap-4 py-4 first:pt-0 last:pb-0">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-hover text-ink-500">
                  <HandCoins className="h-4 w-4" strokeWidth={1.75} />
                </div>
                <div className="min-w-[220px] flex-1">
                  <Link to={`/debts/${d.id}`} className="text-[17px] font-medium text-ink-900 hover:text-accent">
                    {d.counterparty_name}
                  </Link>
                  <span className="ml-2 text-sm text-ink-500">{d.direction === "i_owe" ? "я должен" : "должны мне"}</span>
                  <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-ink-500">
                    <DueBadge debt={d} />
                    {d.due_date && <span>срок {formatDate(d.due_date)}</span>}
                  </p>
                  <div className="mt-2 max-w-sm">
                    <DebtProgress debt={d} compact />
                  </div>
                </div>
                <div className="text-right">
                  <p className="tabular text-lg font-semibold text-ink-900">{formatMoney(d.remaining)}</p>
                  <p className="tabular text-sm text-ink-500">
                    из {formatMoney(d.principal)} · {Math.min(100, Math.max(0, d.paid_percent))}%
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {d.status !== "paid" && (
                    <Button variant="secondary" size="sm" onClick={() => setPayingDebt(d)}>
                      Погасить
                    </Button>
                  )}
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={() => {
                      setDeleteError(null);
                      setDeleting(d);
                    }}
                  >
                    Удалить
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {formOpen && (
        <DebtFormModal
          onClose={() => setFormOpen(false)}
          onSaved={() => {
            setFormOpen(false);
            invalidate();
          }}
        />
      )}
      {payingDebt && (
        <DebtPaymentModal
          debt={payingDebt}
          onClose={() => setPayingDebt(null)}
          onSaved={() => {
            setPayingDebt(null);
            invalidate();
          }}
        />
      )}
      {deleting && (
        <ConfirmModal
          title={`Удалить долг «${deleting.counterparty_name}»?`}
          pending={remove.isPending}
          error={deleteError}
          onConfirm={() => remove.mutate(deleting.id)}
          onClose={() => setDeleting(null)}
        >
          <p>Вместе с долгом удалятся его платежи и связанные с ними операции в журнале.</p>
        </ConfirmModal>
      )}
    </div>
  );
}
