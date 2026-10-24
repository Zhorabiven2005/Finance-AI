import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { FormField, Input, Select } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { errorMessage, FormError } from "@/lib/api/client";
import { budgetsApi, type Budget } from "@/lib/api/budgets";
import { categoriesApi } from "@/lib/api/categories";
import { systemApi } from "@/lib/api/system";
import { orderCategoriesForSelect } from "@/lib/categoryTree";
import { parseToMinor, resolveCurrency, RUB } from "@/lib/money";

const MONTH_NAMES = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];

export function BudgetFormModal({
  budget,
  defaultYear,
  defaultMonth,
  onClose,
  onSaved,
}: {
  budget: Budget | null;
  defaultYear: number;
  defaultMonth: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = budget !== null;
  const { data: categories } = useQuery({
    queryKey: ["categories", "expense"],
    queryFn: () => categoriesApi.list({ type: "expense" }),
  });
  const orderedCategories = useMemo(() => orderCategoriesForSelect(categories ?? []), [categories]);
  const { data: currencies } = useQuery({ queryKey: ["currencies"], queryFn: systemApi.currencies });

  const [categoryId, setCategoryId] = useState(budget ? String(budget.category_id) : "");
  const [currency, setCurrency] = useState(budget?.amount.currency ?? "RUB");
  const [amount, setAmount] = useState(budget ? String(budget.amount.minor / 100) : "");
  const [year, setYear] = useState(budget?.year ?? defaultYear);
  const [month, setMonth] = useState(budget?.month ?? defaultMonth);
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: async () => {
      const minor = parseToMinor(amount, resolveCurrency(currency));
      if (minor === null || minor <= 0) throw new FormError("Некорректная сумма бюджета");

      if (isEdit) {
        return budgetsApi.update(budget.id, { amount_minor: minor });
      }
      if (!categoryId) throw new FormError("Выберите категорию");
      return budgetsApi.create({
        category_id: Number(categoryId),
        amount_minor: minor,
        currency,
        year,
        month,
      });
    },
    onSuccess: onSaved,
    onError: (err) => setError(errorMessage(err, "Не удалось сохранить бюджет")),
  });

  return (
    <Modal title={isEdit ? "Изменить бюджет" : "Новый бюджет"} onClose={onClose}>
      <form
        className="flex flex-col gap-5"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          save.mutate();
        }}
      >
        {isEdit ? (
          <div className="rounded-lg border border-border bg-page px-3.5 py-2.5 text-[15px] text-ink-900">
            {budget.category_name} · {MONTH_NAMES[budget.month - 1]} {budget.year}
          </div>
        ) : (
          <>
            <FormField label="Категория">
              <Select value={categoryId} onChange={(e) => setCategoryId(e.target.value)} required autoFocus>
                <option value="" disabled>
                  Выберите категорию расходов
                </option>
                {orderedCategories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.parent_id ? `— ${c.name}` : c.name}
                  </option>
                ))}
              </Select>
            </FormField>

            <div className="grid grid-cols-2 gap-5">
              <FormField label="Месяц">
                <Select value={month} onChange={(e) => setMonth(Number(e.target.value))}>
                  {MONTH_NAMES.map((name, i) => (
                    <option key={name} value={i + 1}>
                      {name}
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField label="Год">
                <Input
                  type="number"
                  value={year}
                  onChange={(e) => setYear(Number(e.target.value))}
                  min={2000}
                  max={2100}
                />
              </FormField>
            </div>
          </>
        )}

        <div className="grid grid-cols-2 gap-5">
          <FormField label="Сумма">
            <Input
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              inputMode="decimal"
              placeholder="0"
              required
            />
          </FormField>
          <FormField label="Валюта">
            <Select
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              disabled={isEdit}
            >
              {(currencies ?? [RUB]).map((c) => (
                <option key={c.code} value={c.code}>
                  {c.code}
                </option>
              ))}
            </Select>
          </FormField>
        </div>

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
