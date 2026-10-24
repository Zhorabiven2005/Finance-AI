import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { FormField, Input, Select, Textarea } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { accountsApi } from "@/lib/api/accounts";
import { errorMessage, FormError } from "@/lib/api/client";
import { categoriesApi } from "@/lib/api/categories";
import {
  recurringTransactionsApi,
  type Frequency,
  type RecurringTransaction,
  type RecurringType,
} from "@/lib/api/recurringTransactions";
import { orderCategoriesForSelect } from "@/lib/categoryTree";
import { parseToMinor, resolveCurrency } from "@/lib/money";

const FREQUENCY_OPTIONS: { value: Frequency; label: string }[] = [
  { value: "daily", label: "Ежедневно" },
  { value: "weekly", label: "Еженедельно" },
  { value: "monthly", label: "Ежемесячно" },
  { value: "yearly", label: "Ежегодно" },
];

export function RecurringFormModal({
  rule,
  onClose,
  onSaved,
}: {
  rule: RecurringTransaction | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = rule !== null;
  const { data: accounts } = useQuery({ queryKey: ["accounts"], queryFn: () => accountsApi.list(false) });

  const [type, setType] = useState<RecurringType>(rule?.type ?? "expense");
  const { data: categories } = useQuery({
    queryKey: ["categories", type],
    queryFn: () => categoriesApi.list({ type }),
  });
  const orderedCategories = useMemo(() => orderCategoriesForSelect(categories ?? []), [categories]);

  const [accountId, setAccountId] = useState(rule ? String(rule.account_id) : "");
  const [categoryId, setCategoryId] = useState(rule ? String(rule.category_id) : "");
  const [amount, setAmount] = useState(rule ? String(rule.amount.minor / 100) : "");
  const [comment, setComment] = useState(rule?.comment ?? "");
  const [startDate, setStartDate] = useState(rule?.start_date ?? new Date().toISOString().slice(0, 10));
  const [endDate, setEndDate] = useState(rule?.end_date ?? "");
  const [frequency, setFrequency] = useState<Frequency>(rule?.frequency ?? "monthly");
  const [nextRunDate, setNextRunDate] = useState(rule?.next_run_date ?? "");
  const [error, setError] = useState<string | null>(null);

  const selectedAccount = useMemo(
    () => accounts?.find((a) => String(a.id) === accountId),
    [accounts, accountId],
  );

  const save = useMutation({
    mutationFn: async () => {
      if (!accountId) throw new FormError("Выберите счёт");
      if (!categoryId) throw new FormError("Выберите категорию");
      const currency = resolveCurrency(selectedAccount?.currency ?? "RUB");
      const minor = parseToMinor(amount, currency);
      if (minor === null || minor <= 0) throw new FormError("Некорректная сумма");

      if (isEdit) {
        return recurringTransactionsApi.update(rule.id, {
          account_id: Number(accountId),
          category_id: Number(categoryId),
          amount_minor: minor,
          comment: comment.trim() || null,
          end_date: endDate || null,
        });
      }
      return recurringTransactionsApi.create({
        type,
        account_id: Number(accountId),
        category_id: Number(categoryId),
        amount_minor: minor,
        comment: comment.trim() || null,
        start_date: startDate,
        end_date: endDate || null,
        frequency,
        next_run_date: nextRunDate || null,
      });
    },
    onSuccess: onSaved,
    onError: (err) => setError(errorMessage(err, "Не удалось сохранить регулярную операцию")),
  });

  return (
    <Modal title={isEdit ? "Изменить регулярную операцию" : "Новая регулярная операция"} onClose={onClose}>
      <form
        className="flex flex-col gap-5"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          save.mutate();
        }}
      >
        {!isEdit && (
          <FormField label="Тип">
            <Select
              value={type}
              onChange={(e) => {
                setType(e.target.value as RecurringType);
                setCategoryId("");
              }}
            >
              <option value="expense">Расход</option>
              <option value="income">Доход</option>
            </Select>
          </FormField>
        )}

        <div className="grid grid-cols-2 gap-5">
          <FormField label="Счёт">
            <Select value={accountId} onChange={(e) => setAccountId(e.target.value)} required autoFocus>
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
        </div>

        <FormField label="Сумма">
          <Input
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            inputMode="decimal"
            placeholder="0"
            required
          />
        </FormField>

        {!isEdit && (
          <div className="grid grid-cols-2 gap-5">
            <FormField label="Дата начала">
              <Input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                required
              />
            </FormField>
            <FormField label="Периодичность">
              <Select value={frequency} onChange={(e) => setFrequency(e.target.value as Frequency)}>
                {FREQUENCY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </FormField>
          </div>
        )}

        <div className="grid grid-cols-2 gap-5">
          <FormField label="Дата окончания (необязательно)">
            <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </FormField>
          {!isEdit && (
            <FormField label="Дата следующей операции">
              <Input
                type="date"
                value={nextRunDate}
                onChange={(e) => setNextRunDate(e.target.value)}
                placeholder={startDate}
              />
            </FormField>
          )}
        </div>

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
