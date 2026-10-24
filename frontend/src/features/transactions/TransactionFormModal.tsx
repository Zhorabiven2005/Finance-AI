import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { FormField, Input, Select, Textarea } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { accountsApi } from "@/lib/api/accounts";
import { categoriesApi } from "@/lib/api/categories";
import { errorMessage, FormError } from "@/lib/api/client";
import { transactionsApi, type Transaction, type TransactionType } from "@/lib/api/transactions";
import { orderCategoriesForSelect } from "@/lib/categoryTree";
import { parseToMinor, resolveCurrency } from "@/lib/money";

function toDatetimeLocal(iso?: string): string {
  const d = iso ? new Date(iso) : new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const TYPE_LABEL: Record<TransactionType, string> = { income: "доход", expense: "расход" };

export function TransactionFormModal({
  type,
  transaction,
  onClose,
  onSaved,
}: {
  type: TransactionType;
  transaction: Transaction | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = transaction !== null;
  const { data: accounts } = useQuery({ queryKey: ["accounts"], queryFn: () => accountsApi.list(false) });
  const { data: categories } = useQuery({
    queryKey: ["categories", type],
    queryFn: () => categoriesApi.list({ type }),
  });

  const [accountId, setAccountId] = useState<string>(
    transaction ? String(transaction.account_id) : "",
  );
  const [categoryId, setCategoryId] = useState<string>(
    transaction ? String(transaction.category_id) : "",
  );
  const [amount, setAmount] = useState(
    transaction ? String(transaction.amount.minor / 100) : "",
  );
  const [occurredAt, setOccurredAt] = useState(toDatetimeLocal(transaction?.occurred_at));
  const [comment, setComment] = useState(transaction?.comment ?? "");
  const [error, setError] = useState<string | null>(null);

  const selectedAccount = useMemo(
    () => accounts?.find((a) => String(a.id) === accountId),
    [accounts, accountId],
  );

  const orderedCategories = useMemo(() => orderCategoriesForSelect(categories ?? []), [categories]);

  const save = useMutation({
    mutationFn: async () => {
      if (!accountId) throw new FormError("Выберите счёт");
      if (!categoryId) throw new FormError("Выберите категорию");
      const currency = resolveCurrency(selectedAccount?.currency ?? "RUB");
      const minor = parseToMinor(amount, currency);
      if (minor === null || minor <= 0) throw new FormError("Некорректная сумма");

      const payload = {
        account_id: Number(accountId),
        category_id: Number(categoryId),
        type,
        amount_minor: minor,
        occurred_at: new Date(occurredAt).toISOString(),
        comment: comment.trim() || null,
      };
      return isEdit ? transactionsApi.update(transaction.id, payload) : transactionsApi.create(payload);
    },
    onSuccess: onSaved,
    onError: (err) => setError(errorMessage(err, "Не удалось сохранить операцию")),
  });

  return (
    <Modal
      title={isEdit ? `Изменить ${TYPE_LABEL[type]}` : `Новый ${TYPE_LABEL[type]}`}
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
        <FormField label="Счёт">
          <Select value={accountId} onChange={(e) => setAccountId(e.target.value)} required>
            <option value="" disabled>
              Выберите счёт
            </option>
            {(accounts ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </Select>
        </FormField>

        <FormField label="Категория">
          <Select value={categoryId} onChange={(e) => setCategoryId(e.target.value)} required>
            <option value="" disabled>
              Выберите категорию
            </option>
            {orderedCategories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.parent_id ? `— ${c.name}` : c.name}
              </option>
            ))}
          </Select>
        </FormField>

        <FormField label="Сумма">
          <Input
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            inputMode="decimal"
            placeholder="0"
            required
            autoFocus
          />
        </FormField>

        <FormField label="Дата и время">
          <Input
            type="datetime-local"
            value={occurredAt}
            onChange={(e) => setOccurredAt(e.target.value)}
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
            Сохранить
          </Button>
        </div>
      </form>
    </Modal>
  );
}
