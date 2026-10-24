import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LoadError } from "@/components/ui/Card";
import { accountsApi } from "@/lib/api/accounts";
import { debtsApi, type Debt, type DebtPayment } from "@/lib/api/debts";
import { debtDueLabel } from "@/lib/debtDue";
import { formatMoney } from "@/lib/money";

export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso.length === 10 ? `${iso}T00:00:00` : iso).toLocaleDateString("ru-RU");
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Платёж со счётом — ещё и операция в журнале, поэтому после любого
 * изменения долга или платежа обновляется всё, что строится на операциях. */
export function useInvalidateDebts() {
  const queryClient = useQueryClient();
  return () => {
    for (const key of ["debts", "debt", "debt-payments", "accounts", "dashboard", "transactions", "analytics", "budgets", "notifications"]) {
      queryClient.invalidateQueries({ queryKey: [key] });
    }
  };
}

export function DueBadge({ debt }: { debt: Debt }) {
  const { label, tone } = debtDueLabel(debt);
  return <Badge tone={tone}>{label}</Badge>;
}

export function DebtProgress({ debt, compact = false }: { debt: Debt; compact?: boolean }) {
  const percent = Math.min(100, Math.max(0, debt.paid_percent));
  return (
    <div>
      <div className={compact ? "h-1.5 w-full overflow-hidden rounded-full bg-surface-hover" : "h-2.5 w-full overflow-hidden rounded-full bg-surface-hover"}>
        <div
          className={`h-full rounded-full ${debt.status === "paid" ? "bg-success" : "bg-accent"}`}
          style={{ width: `${percent}%` }}
          role="progressbar"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Прогресс погашения"
        />
      </div>
      {!compact && (
        <p className="mt-1.5 text-sm text-ink-500">
          Погашено {formatMoney(debt.paid)} из {formatMoney(debt.principal)} · <span className="tabular">{percent}%</span>
        </p>
      )}
    </div>
  );
}

export function PaymentHistory({
  debt,
  onEdit,
  onDelete,
}: {
  debt: Debt;
  onEdit: (p: DebtPayment) => void;
  onDelete: (p: DebtPayment) => void;
}) {
  const { data: payments, isPending, isError, isFetching, refetch } = useQuery({
    queryKey: ["debt-payments", debt.id],
    queryFn: () => debtsApi.payments(debt.id),
  });
  const { data: accounts } = useQuery({
    queryKey: ["accounts", "with-inactive"],
    queryFn: () => accountsApi.list(true),
  });
  const accountName = (id: number | null) =>
    id === null ? "без счёта" : (accounts?.find((a) => a.id === id)?.name ?? `#${id}`);

  if (isPending) return <p className="py-3 text-sm text-ink-500">Загрузка…</p>;
  if (isError) return <LoadError onRetry={() => refetch()} retrying={isFetching} />;
  if (!payments || payments.length === 0) return <p className="py-3 text-sm text-ink-500">Платежей пока нет.</p>;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-[15px]">
        <thead className="text-sm text-ink-500">
          <tr className="border-b border-border">
            <th className="py-2 pr-4 font-medium">Дата</th>
            <th className="py-2 pr-4 text-right font-medium">Сумма</th>
            <th className="py-2 pr-4 font-medium">Счёт</th>
            <th className="py-2 pr-4 font-medium">Комментарий</th>
            <th className="py-2 pr-4 font-medium">Операция</th>
            <th className="py-2" />
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {payments.map((p) => (
            <tr key={p.id} data-testid="payment-row">
              <td className="py-3 pr-4 text-ink-900">{formatDateTime(p.paid_at)}</td>
              <td className="tabular py-3 pr-4 text-right font-medium text-ink-900">{formatMoney(p.amount)}</td>
              <td className="py-3 pr-4 text-ink-700">{accountName(p.account_id)}</td>
              <td className="py-3 pr-4 text-ink-500">{p.comment ?? ""}</td>
              <td className="py-3 pr-4 text-sm">
                {p.transaction_id ? (
                  <Link to={`/transactions?tx=${p.transaction_id}`} className="text-accent hover:underline">
                    №{p.transaction_id} в журнале
                  </Link>
                ) : (
                  <span className="text-ink-400">не влияет на счёт</span>
                )}
              </td>
              <td className="py-3">
                <div className="flex justify-end gap-2">
                  <Button variant="ghost" size="sm" onClick={() => onEdit(p)} aria-label="Изменить платёж" title="Изменить платёж">
                    <Pencil className="h-3.5 w-3.5" strokeWidth={1.75} />
                  </Button>
                  <Button variant="danger" size="sm" onClick={() => onDelete(p)} aria-label="Удалить платёж" title="Удалить платёж">
                    <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
