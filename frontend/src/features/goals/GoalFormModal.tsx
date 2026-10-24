import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { FormField, Input, Select, Textarea } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { errorMessage, FormError } from "@/lib/api/client";
import { goalsApi, type Goal } from "@/lib/api/goals";
import { systemApi } from "@/lib/api/system";
import { parseToMinor, resolveCurrency, RUB } from "@/lib/money";

export function GoalFormModal({
  goal,
  onClose,
  onSaved,
}: {
  goal: Goal | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = goal !== null;
  const { data: currencies } = useQuery({ queryKey: ["currencies"], queryFn: systemApi.currencies });

  const [name, setName] = useState(goal?.name ?? "");
  const [description, setDescription] = useState(goal?.description ?? "");
  const [currency, setCurrency] = useState(goal?.currency ?? "RUB");
  const [targetAmount, setTargetAmount] = useState(
    goal ? String(goal.target.minor / 10 ** resolveCurrency(goal.currency).exponent) : "",
  );
  const [targetDate, setTargetDate] = useState(goal?.target_date ?? "");
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: async () => {
      if (!name.trim()) throw new FormError("Укажите название цели");
      const minor = parseToMinor(targetAmount, resolveCurrency(currency));
      if (minor === null || minor <= 0) throw new FormError("Некорректная сумма цели");

      if (isEdit) {
        return goalsApi.update(goal.id, {
          name: name.trim(),
          description: description.trim() || null,
          target_amount_minor: minor,
          target_date: targetDate || null,
        });
      }
      return goalsApi.create({
        name: name.trim(),
        description: description.trim() || null,
        target_amount_minor: minor,
        currency,
        target_date: targetDate || null,
      });
    },
    onSuccess: onSaved,
    onError: (err) => setError(errorMessage(err, "Не удалось сохранить цель")),
  });

  return (
    <Modal title={isEdit ? "Изменить цель" : "Новая цель"} onClose={onClose}>
      <form
        className="flex flex-col gap-5"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          save.mutate();
        }}
      >
        <FormField label="Название">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={150}
            placeholder="Например, «MacBook»"
            autoFocus
          />
        </FormField>

        <div className="grid grid-cols-2 gap-5">
          <FormField label="Целевая сумма">
            <Input
              value={targetAmount}
              onChange={(e) => setTargetAmount(e.target.value)}
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

        <FormField label="Срок (необязательно)">
          <Input type="date" value={targetDate} onChange={(e) => setTargetDate(e.target.value)} />
        </FormField>

        <FormField label="Описание (необязательно)">
          <Textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            maxLength={1000}
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
