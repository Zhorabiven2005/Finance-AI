import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { FormField, Input, Textarea } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { errorMessage, FormError } from "@/lib/api/client";
import { goalsApi, type Goal, type GoalEntryType } from "@/lib/api/goals";
import { formatMoney, parseToMinor, resolveCurrency } from "@/lib/money";

function nowLocal(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const TITLE: Record<GoalEntryType, string> = {
  contribution: "Пополнение цели",
  withdrawal: "Списание с цели",
};

export function GoalEntryModal({
  goal,
  type,
  onClose,
  onSaved,
}: {
  goal: Goal;
  type: GoalEntryType;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [amount, setAmount] = useState("");
  const [occurredAt, setOccurredAt] = useState(nowLocal());
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: async () => {
      const currency = resolveCurrency(goal.currency);
      const minor = parseToMinor(amount, currency);
      if (minor === null || minor <= 0) throw new FormError("Некорректная сумма");
      return goalsApi.addEntry(goal.id, {
        type,
        amount_minor: minor,
        occurred_at: new Date(occurredAt).toISOString(),
        comment: comment.trim() || null,
      });
    },
    onSuccess: onSaved,
    onError: (err) => setError(errorMessage(err, "Не удалось сохранить операцию по цели")),
  });

  return (
    <Modal title={`${TITLE[type]}: ${goal.name}`} onClose={onClose}>
      <form
        className="flex flex-col gap-5"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          save.mutate();
        }}
      >
        <p className="text-sm text-ink-500">
          Накоплено: <span className="tabular font-medium text-ink-900">{formatMoney(goal.saved)}</span>
          {" из "}
          <span className="tabular font-medium text-ink-900">{formatMoney(goal.target)}</span>
        </p>

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

        <FormField label="Дата">
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
            {type === "contribution" ? "Пополнить" : "Списать"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
