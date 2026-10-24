import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Pencil } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { Card, CardHeader, EmptyState } from "@/components/ui/Card";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { errorMessage } from "@/lib/api/client";
import { debtsApi, type DebtPayment } from "@/lib/api/debts";
import { formatMoney } from "@/lib/money";

import { DebtFormModal } from "./DebtFormModal";
import { DebtPaymentModal } from "./DebtPaymentModal";
import { DebtProgress, DueBadge, PaymentHistory, formatDate, useInvalidateDebts } from "./debtShared";

function Stat({ label, value, tone = "text-ink-900" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-border bg-page/60 px-4 py-3">
      <p className="text-sm text-ink-500">{label}</p>
      <p className={`tabular mt-1 text-xl font-semibold ${tone}`}>{value}</p>
    </div>
  );
}

export function DebtDetailPage() {
  const { debtId } = useParams();
  const id = Number(debtId);
  const navigate = useNavigate();
  const invalidate = useInvalidateDebts();

  const [editing, setEditing] = useState(false);
  const [paying, setPaying] = useState(false);
  const [editingPayment, setEditingPayment] = useState<DebtPayment | null>(null);
  const [deletingPayment, setDeletingPayment] = useState<DebtPayment | null>(null);
  const [deletingDebt, setDeletingDebt] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: debt, isPending, isError } = useQuery({
    queryKey: ["debt", id],
    queryFn: () => debtsApi.get(id),
    enabled: Number.isFinite(id),
    retry: false,
  });

  const removePayment = useMutation({
    mutationFn: (p: DebtPayment) => debtsApi.removePayment(id, p.id),
    onSuccess: () => {
      setDeletingPayment(null);
      invalidate();
    },
    onError: (err) => setError(errorMessage(err, "Не удалось удалить платёж")),
  });
  const removeDebt = useMutation({
    mutationFn: () => debtsApi.remove(id),
    onSuccess: () => {
      invalidate();
      navigate("/debts");
    },
    onError: (err) => setError(errorMessage(err, "Не удалось удалить долг")),
  });

  const back = (
    <Link to="/debts" className="inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline">
      <ArrowLeft className="h-4 w-4" strokeWidth={1.75} />
      Все долги
    </Link>
  );

  if (isPending) return <p className="text-[15px] text-ink-500">Загрузка…</p>;
  if (isError || !debt) {
    return (
      <div className="flex flex-col gap-4">
        {back}
        <Card>
          <EmptyState>Долг не найден — возможно, он был удалён.</EmptyState>
        </Card>
      </div>
    );
  }

  const isPaid = debt.status === "paid";

  return (
    <div className="flex flex-col gap-6">
      {back}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-[28px] font-semibold tracking-tight text-ink-900">{debt.counterparty_name}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-[15px] text-ink-500">
            {debt.direction === "i_owe" ? "Я должен" : "Мне должны"} · {debt.remaining.currency}
            <DueBadge debt={debt} />
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {!isPaid && <Button onClick={() => setPaying(true)}>Погасить</Button>}
          <Button variant="secondary" onClick={() => setEditing(true)}>
            <Pencil className="h-4 w-4" strokeWidth={1.75} />
            Изменить
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              setError(null);
              setDeletingDebt(true);
            }}
          >
            Удалить
          </Button>
        </div>
      </div>

      <Card>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Первоначальная сумма" value={formatMoney(debt.principal)} />
          <Stat label="Погашено" value={formatMoney(debt.paid)} tone="text-success" />
          <Stat label="Остаток" value={formatMoney(debt.remaining)} tone={isPaid ? "text-success" : "text-ink-900"} />
          <Stat label="Прогресс" value={`${Math.min(100, Math.max(0, debt.paid_percent))}%`} />
        </div>
        <div className="mt-5">
          <DebtProgress debt={debt} />
        </div>
        <dl className="mt-5 grid gap-x-8 gap-y-2 text-[15px] md:grid-cols-2">
          <div className="flex justify-between gap-4">
            <dt className="text-ink-500">Срок погашения</dt>
            <dd className="text-ink-900">{debt.due_date ? formatDate(debt.due_date) : "не задан"}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-ink-500">Создан</dt>
            <dd className="text-ink-900">{formatDate(debt.created_at)}</dd>
          </div>
          {debt.comment && (
            <div className="flex justify-between gap-4 md:col-span-2">
              <dt className="text-ink-500">Комментарий</dt>
              <dd className="text-right text-ink-900">{debt.comment}</dd>
            </div>
          )}
        </dl>
        <p className="mt-4 text-sm text-ink-400">
          Срок относится ко всему долгу. Обязательного графика платежей приложение не знает и не придумывает.
        </p>
      </Card>

      <Card>
        <CardHeader title="История платежей" />
        <PaymentHistory
          debt={debt}
          onEdit={setEditingPayment}
          onDelete={(p) => {
            setError(null);
            setDeletingPayment(p);
          }}
        />
      </Card>

      {editing && (
        <DebtFormModal
          debt={debt}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            invalidate();
          }}
        />
      )}
      {(paying || editingPayment) && (
        <DebtPaymentModal
          debt={debt}
          payment={editingPayment}
          onClose={() => {
            setPaying(false);
            setEditingPayment(null);
          }}
          onSaved={() => {
            setPaying(false);
            setEditingPayment(null);
            invalidate();
          }}
        />
      )}
      {deletingPayment && (
        <ConfirmModal
          title="Удалить платёж?"
          pending={removePayment.isPending}
          error={error}
          onConfirm={() => removePayment.mutate(deletingPayment)}
          onClose={() => setDeletingPayment(null)}
        >
          <p>
            Платёж {formatMoney(deletingPayment.amount)} будет удалён, остаток долга вернётся, а связанная операция
            исчезнет из журнала и баланс счёта восстановится.
          </p>
        </ConfirmModal>
      )}
      {deletingDebt && (
        <ConfirmModal
          title={`Удалить долг «${debt.counterparty_name}»?`}
          pending={removeDebt.isPending}
          error={error}
          onConfirm={() => removeDebt.mutate()}
          onClose={() => setDeletingDebt(false)}
        >
          <p>Вместе с долгом удалятся его платежи и связанные с ними операции в журнале.</p>
        </ConfirmModal>
      )}
    </div>
  );
}
