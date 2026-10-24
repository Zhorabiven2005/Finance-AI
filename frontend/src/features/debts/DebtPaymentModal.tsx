import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { FormField, Input, Select, Textarea } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { accountsApi } from "@/lib/api/accounts";
import { errorMessage, FormError } from "@/lib/api/client";
import { debtsApi, type Debt, type DebtPayment } from "@/lib/api/debts";
import { formatMoney, parseToMinor, resolveCurrency } from "@/lib/money";

function nowLocal(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function DebtPaymentModal({
  debt,
  payment = null,
  onClose,
  onSaved,
}: {
  debt: Debt;
  /** Если передан — режим изменения существующего платежа. */
  payment?: DebtPayment | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { data: accounts } = useQuery({ queryKey: ["accounts"], queryFn: () => accountsApi.list(false) });
  const matchingAccounts = (accounts ?? []).filter((a) => a.currency === debt.remaining.currency);

  const isEdit = payment !== null;
  const exponent = resolveCurrency(debt.remaining.currency).exponent;
  // При изменении платежа доступно «остаток + сумма самого платежа».
  const maxMinor = debt.remaining.minor + (payment?.amount.minor ?? 0);

  const [amount, setAmount] = useState(String((payment?.amount.minor ?? debt.remaining.minor) / 10 ** exponent));
  const [accountId, setAccountId] = useState(payment?.account_id ? String(payment.account_id) : "");
  const [paidAt, setPaidAt] = useState(payment ? toLocalInput(payment.paid_at) : nowLocal());
  const [comment, setComment] = useState(payment?.comment ?? "");
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: async () => {
      const currency = resolveCurrency(debt.remaining.currency);
      const minor = parseToMinor(amount, currency);
      if (minor === null || minor <= 0) throw new FormError("Некорректная сумма");
      const body = {
        amount_minor: minor,
        paid_at: new Date(paidAt).toISOString(),
        account_id: accountId ? Number(accountId) : null,
        comment: comment.trim() || null,
      };
      return isEdit ? debtsApi.updatePayment(debt.id, payment.id, body) : debtsApi.addPayment(debt.id, body);
    },
    onSuccess: onSaved,
    onError: (err) => setError(errorMessage(err, "Не удалось провести погашение")),
  });

  return (
    <Modal
      title={`${isEdit ? "Изменить платёж" : "Погашение долга"}: ${debt.counterparty_name}`}
      onClose={onClose}
    >
      <form
        className="flex flex-col gap-5"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          save.mutate();
        }}
      >
        <p className="text-sm text-ink-500">
          {isEdit ? "Максимум для этого платежа:" : "Остаток долга:"}{" "}
          <span className="tabular font-medium text-ink-900">
            {formatMoney({ minor: maxMinor, currency: debt.remaining.currency })}
          </span>
        </p>

        <FormField label="Сумма погашения">
          <Input
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            inputMode="decimal"
            required
            autoFocus
          />
        </FormField>

        <FormField label="Счёт (необязательно)">
          <Select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            <option value="">Не указывать (не влияет на баланс счёта и журнал операций)</option>
            {matchingAccounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </Select>
        </FormField>

        <FormField label="Дата">
          <Input
            type="datetime-local"
            value={paidAt}
            onChange={(e) => setPaidAt(e.target.value)}
            required
          />
        </FormField>

        <FormField label="Комментарий (необязательно)">
          <Textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={2}
            maxLength={500}
          />
        </FormField>

        {error && <p className="text-sm text-danger">{error}</p>}

        <div className="mt-2 flex justify-end gap-3">
          <Button type="button" variant="secondary" onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" disabled={save.isPending}>
            {isEdit ? "Сохранить" : "Погасить"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
