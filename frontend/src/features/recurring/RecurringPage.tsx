import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { PlayCircle } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader, EmptyState, LoadError } from "@/components/ui/Card";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { errorMessage } from "@/lib/api/client";
import {
  recurringTransactionsApi,
  type Frequency,
  type RecurringTransaction,
} from "@/lib/api/recurringTransactions";
import { CategoryIcon } from "@/lib/categoryIcons";
import { formatMoney } from "@/lib/money";

import { RecurringFormModal } from "./RecurringFormModal";

const FREQUENCY_LABEL: Record<Frequency, string> = {
  daily: "Ежедневно",
  weekly: "Еженедельно",
  monthly: "Ежемесячно",
  yearly: "Ежегодно",
};

function formatDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

export function RecurringPage() {
  const queryClient = useQueryClient();
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<RecurringTransaction | null>(null);
  const [notice, setNotice] = useState<{ title: string; text: string } | null>(null);
  const [deleting, setDeleting] = useState<RecurringTransaction | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const showError = (err: unknown) =>
    setNotice({ title: "Не удалось выполнить действие", text: errorMessage(err) });

  const { data: rules, isPending, isError, isFetching, refetch } = useQuery({
    queryKey: ["recurring-transactions"],
    queryFn: () => recurringTransactionsApi.list(),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["recurring-transactions"] });
    queryClient.invalidateQueries({ queryKey: ["transactions"] });
    queryClient.invalidateQueries({ queryKey: ["accounts"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    queryClient.invalidateQueries({ queryKey: ["budgets"] });
    queryClient.invalidateQueries({ queryKey: ["analytics"] });
  };

  const toggleActive = useMutation({
    mutationFn: (rule: RecurringTransaction) =>
      recurringTransactionsApi.update(rule.id, { is_active: !rule.is_active }),
    onSuccess: invalidate,
    onError: showError,
  });

  const remove = useMutation({
    mutationFn: (rule: RecurringTransaction) => recurringTransactionsApi.remove(rule.id),
    onSuccess: () => {
      setDeleting(null);
      invalidate();
    },
    onError: (err) => setDeleteError(errorMessage(err, "Не удалось удалить регулярную операцию")),
  });

  const process = useMutation({
    mutationFn: () => recurringTransactionsApi.process(),
    onSuccess: (result) => {
      invalidate();
      setNotice({
        title: "Обработка завершена",
        text:
          result.created_transactions > 0
            ? `Создано операций: ${result.created_transactions}`
            : "Новых операций нет — все правила уже обработаны.",
      });
    },
    onError: showError,
  });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-[28px] font-semibold tracking-tight text-ink-900">
          Регулярные операции
        </h1>
        <div className="flex gap-3">
          <Button variant="secondary" onClick={() => process.mutate()} disabled={process.isPending}>
            <PlayCircle className="h-4 w-4" strokeWidth={1.75} />
            Обработать сейчас
          </Button>
          <Button
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            + Добавить
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader title="Все правила" />
        {isPending ? (
          <p className="text-[15px] text-ink-500">Загрузка…</p>
        ) : isError ? (
          <LoadError onRetry={() => refetch()} retrying={isFetching} />
        ) : !rules || rules.length === 0 ? (
          <EmptyState>Регулярных операций пока нет.</EmptyState>
        ) : (
          <ul className="divide-y divide-border">
            {rules.map((r) => (
              <li key={r.id} className="flex items-center gap-4 py-4 first:pt-0 last:pb-0">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-hover text-ink-500">
                  <CategoryIcon name={r.category_name} type={r.type} icon={r.category_icon} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[15px] font-medium text-ink-900">
                    {r.category_name}
                    <span className="font-normal text-ink-500"> · {r.account_name}</span>
                  </p>
                  <p className="text-sm text-ink-500">
                    {FREQUENCY_LABEL[r.frequency]} · Следующая операция: {formatDate(r.next_run_date)}
                  </p>
                </div>
                <span
                  className={`tabular text-[15px] font-semibold ${r.type === "income" ? "text-success" : "text-ink-900"}`}
                >
                  {r.type === "income" ? "+" : "−"}
                  {formatMoney(r.amount)}
                </span>
                <Badge tone={r.is_active ? "ok" : "neutral"}>
                  {r.is_active ? "Активна" : "Остановлена"}
                </Badge>
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={toggleActive.isPending && toggleActive.variables?.id === r.id}
                    onClick={() => toggleActive.mutate(r)}
                  >
                    {r.is_active ? "Остановить" : "Возобновить"}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setEditing(r);
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
                      setDeleting(r);
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

      {deleting && (
        <ConfirmModal
          title={`Удалить регулярную операцию «${deleting.category_name}»?`}
          pending={remove.isPending}
          error={deleteError}
          onConfirm={() => remove.mutate(deleting)}
          onClose={() => setDeleting(null)}
        >
          <p>Новые операции по этому правилу больше не создадутся. Уже созданные останутся в журнале.</p>
        </ConfirmModal>
      )}
      {notice && (
        <ConfirmModal title={notice.title} onClose={() => setNotice(null)}>
          {notice.text}
        </ConfirmModal>
      )}

      {formOpen && (
        <RecurringFormModal
          rule={editing}
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
