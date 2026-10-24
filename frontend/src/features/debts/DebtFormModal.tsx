import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { FormField, Input, Select, Textarea } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { errorMessage, FormError } from "@/lib/api/client";
import { debtsApi, type Debt, type DebtDirection } from "@/lib/api/debts";
import { systemApi } from "@/lib/api/system";
import { formatMoney, parseToMinor, resolveCurrency, RUB } from "@/lib/money";

export function DebtFormModal({
  debt = null,
  onClose,
  onSaved,
}: {
  /** Если передан — изменение. Сумма, валюта и направление не меняются:
   * от них зависят платежи и связанные операции. */
  debt?: Debt | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = debt !== null;
  const { data: currencies } = useQuery({ queryKey: ["currencies"], queryFn: systemApi.currencies, enabled: !isEdit });

  const [counterparty, setCounterparty] = useState(debt?.counterparty_name ?? "");
  const [direction, setDirection] = useState<DebtDirection>(debt?.direction ?? "i_owe");
  const [currency, setCurrency] = useState("RUB");
  const [principal, setPrincipal] = useState("");
  const [dueDate, setDueDate] = useState(debt?.due_date ?? "");
  const [comment, setComment] = useState(debt?.comment ?? "");
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: async () => {
      if (!counterparty.trim()) throw new FormError("Укажите имя должника/кредитора");
      if (isEdit) {
        return debtsApi.update(debt.id, {
          counterparty_name: counterparty.trim(),
          due_date: dueDate || null,
          comment: comment.trim() || null,
        });
      }
      const minor = parseToMinor(principal, resolveCurrency(currency));
      if (minor === null || minor <= 0) throw new FormError("Некорректная сумма долга");
      return debtsApi.create({
        counterparty_name: counterparty.trim(),
        direction,
        principal_minor: minor,
        currency,
        due_date: dueDate || null,
        comment: comment.trim() || null,
      });
    },
    onSuccess: onSaved,
    onError: (err) => setError(errorMessage(err, isEdit ? "Не удалось сохранить долг" : "Не удалось создать долг")),
  });

  return (
    <Modal title={isEdit ? "Изменить долг" : "Новый долг"} onClose={onClose}>
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
            {debt.direction === "i_owe" ? "Я должен" : "Мне должны"} · {formatMoney(debt.principal)}
          </div>
        ) : (
          <FormField label="Направление">
            <Select value={direction} onChange={(e) => setDirection(e.target.value as DebtDirection)}>
              <option value="i_owe">Я должен</option>
              <option value="owed_to_me">Мне должны</option>
            </Select>
          </FormField>
        )}

        <FormField label={direction === "i_owe" ? "Кому я должен" : "Кто мне должен"}>
          <Input
            value={counterparty}
            onChange={(e) => setCounterparty(e.target.value)}
            required
            maxLength={200}
            placeholder="Имя"
            autoFocus
          />
        </FormField>

        {!isEdit && (
          <div className="grid grid-cols-2 gap-5">
            <FormField label="Сумма">
              <Input
                value={principal}
                onChange={(e) => setPrincipal(e.target.value)}
                inputMode="decimal"
                placeholder="0"
                required
              />
            </FormField>
            <FormField label="Валюта">
              <Select value={currency} onChange={(e) => setCurrency(e.target.value)}>
                {(currencies ?? [RUB]).map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.code}
                  </option>
                ))}
              </Select>
            </FormField>
          </div>
        )}

        <FormField label="Срок погашения (необязательно)">
          <div className="flex gap-2">
            <Input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} aria-label="Срок погашения" />
            {dueDate && (
              <Button type="button" variant="ghost" size="sm" onClick={() => setDueDate("")}>
                Убрать
              </Button>
            )}
          </div>
        </FormField>

        <FormField label="Комментарий (необязательно)">
          <Textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={2} maxLength={500} />
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
