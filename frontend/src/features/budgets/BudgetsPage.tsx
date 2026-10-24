import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader, EmptyState, LoadError } from "@/components/ui/Card";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { errorMessage } from "@/lib/api/client";
import { budgetsApi, type Budget } from "@/lib/api/budgets";
import {
  BUDGET_STATUS_BADGE_TONE,
  BUDGET_STATUS_BAR_CLASS,
  BUDGET_STATUS_LABEL,
} from "@/lib/budgetStatus";
import { CategoryIcon } from "@/lib/categoryIcons";
import { formatMoney } from "@/lib/money";

import { BudgetFormModal } from "./BudgetFormModal";

function monthLabel(year: number, month: number): string {
  const label = new Date(year, month - 1, 1).toLocaleDateString("ru-RU", {
    month: "long",
    year: "numeric",
  });
  return label.charAt(0).toUpperCase() + label.slice(1);
}

export function BudgetsPage() {
  const queryClient = useQueryClient();
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Budget | null>(null);
  const [deleting, setDeleting] = useState<Budget | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const shiftMonth = (delta: number) => {
    let m = month + delta;
    let y = year;
    if (m < 1) {
      m = 12;
      y -= 1;
    } else if (m > 12) {
      m = 1;
      y += 1;
    }
    setMonth(m);
    setYear(y);
  };

  const { data: budgets, isPending, isError, isFetching, refetch } = useQuery({
    queryKey: ["budgets", year, month],
    queryFn: () => budgetsApi.list(year, month),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["budgets"] });

  const remove = useMutation({
    mutationFn: (budget: Budget) => budgetsApi.remove(budget.id),
    onSuccess: () => {
      setDeleting(null);
      invalidate();
    },
    onError: (err) => setDeleteError(errorMessage(err, "Не удалось удалить бюджет")),
  });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-[28px] font-semibold tracking-tight text-ink-900">Бюджеты</h1>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1 rounded-lg border border-border bg-surface p-1">
            <button
              type="button"
              onClick={() => shiftMonth(-1)}
              className="flex h-8 w-8 items-center justify-center rounded-md text-ink-500 hover:bg-surface-hover hover:text-ink-900"
              aria-label="Предыдущий месяц"
            >
              <ChevronLeft className="h-4 w-4" strokeWidth={1.75} />
            </button>
            <span className="w-40 text-center text-[15px] font-medium text-ink-900">
              {monthLabel(year, month)}
            </span>
            <button
              type="button"
              onClick={() => shiftMonth(1)}
              className="flex h-8 w-8 items-center justify-center rounded-md text-ink-500 hover:bg-surface-hover hover:text-ink-900"
              aria-label="Следующий месяц"
            >
              <ChevronRight className="h-4 w-4" strokeWidth={1.75} />
            </button>
          </div>
          <Button
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            + Добавить бюджет
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader title="Бюджеты на месяц" />
        {isPending ? (
          <p className="text-[15px] text-ink-500">Загрузка…</p>
        ) : isError ? (
          <LoadError onRetry={() => refetch()} retrying={isFetching} />
        ) : !budgets || budgets.length === 0 ? (
          <EmptyState>На этот месяц бюджетов ещё нет — добавьте первый.</EmptyState>
        ) : (
          <ul className="divide-y divide-border">
            {budgets.map((b) => (
              <li key={b.id} className="py-5 first:pt-0 last:pb-0">
                <div className="flex items-center gap-4">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-hover text-ink-500">
                    <CategoryIcon name={b.category_name} type="expense" icon={b.category_icon} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-3">
                      <p className="truncate text-[17px] font-medium text-ink-900">
                        {b.category_name}
                      </p>
                      <Badge tone={BUDGET_STATUS_BADGE_TONE[b.status]}>
                        {BUDGET_STATUS_LABEL[b.status]}
                      </Badge>
                    </div>
                    <p className="tabular text-sm text-ink-500">
                      {formatMoney(b.spent)} из {formatMoney(b.amount)}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setEditing(b);
                        setFormOpen(true);
                      }}
                    >
                      Изменить
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => {
                        setDeleteError(null);
                        setDeleting(b);
                      }}
                    >
                      Удалить
                    </Button>
                  </div>
                </div>

                <div className="mt-3 h-2.5 w-full overflow-hidden rounded-full bg-surface-hover">
                  <div
                    className={`h-full rounded-full transition-all ${BUDGET_STATUS_BAR_CLASS[b.status]}`}
                    style={{ width: `${Math.min(100, Math.max(0, b.usage_percent))}%` }}
                  />
                </div>
                <div className="mt-2 flex items-center justify-between text-sm text-ink-500">
                  <span>Осталось {formatMoney(b.remaining)}</span>
                  <span className="tabular font-medium text-ink-900">{b.usage_percent}%</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {deleting && (
        <ConfirmModal
          title={`Удалить бюджет «${deleting.category_name}»?`}
          pending={remove.isPending}
          error={deleteError}
          onConfirm={() => remove.mutate(deleting)}
          onClose={() => setDeleting(null)}
        >
          <p>
            Лимит на {monthLabel(deleting.year, deleting.month).toLowerCase()} будет удалён. Операции и
            расходы по категории не изменятся.
          </p>
        </ConfirmModal>
      )}
      {formOpen && (
        <BudgetFormModal
          budget={editing}
          defaultYear={year}
          defaultMonth={month}
          onClose={() => setFormOpen(false)}
          onSaved={() => {
            setFormOpen(false);
            invalidate();
          }}
        />
      )}
    </div>
  );
}
