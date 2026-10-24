import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { FormField, Input, Select, Textarea } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { accountsApi } from "@/lib/api/accounts";
import { errorMessage, FormError } from "@/lib/api/client";
import { transfersApi } from "@/lib/api/transfers";
import { parseToMinor, resolveCurrency } from "@/lib/money";

function nowLocal(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function TransferFormModal({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const { data: accounts } = useQuery({ queryKey: ["accounts"], queryFn: () => accountsApi.list(false) });

  const [fromId, setFromId] = useState("");
  const [toId, setToId] = useState("");
  const [amount, setAmount] = useState("");
  const [occurredAt, setOccurredAt] = useState(nowLocal());
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);

  const fromAccount = useMemo(() => accounts?.find((a) => String(a.id) === fromId), [accounts, fromId]);

  const save = useMutation({
    mutationFn: async () => {
      if (!fromId || !toId) throw new FormError("Выберите оба счёта");
      if (fromId === toId) throw new FormError("Счёт-источник и счёт-получатель должны различаться");
      const currency = resolveCurrency(fromAccount?.currency ?? "RUB");
      const minor = parseToMinor(amount, currency);
      if (minor === null || minor <= 0) throw new FormError("Некорректная сумма");
      return transfersApi.create({
        from_account_id: Number(fromId),
        to_account_id: Number(toId),
        amount_minor: minor,
        occurred_at: new Date(occurredAt).toISOString(),
        comment: comment.trim() || null,
      });
    },
    onSuccess: onSaved,
    onError: (err) => setError(errorMessage(err, "Не удалось выполнить перевод")),
  });

  return (
    <Modal title="Перевод между счетами" onClose={onClose}>
      <form
        className="flex flex-col gap-5"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          save.mutate();
        }}
      >
        <FormField label="Со счёта">
          <Select value={fromId} onChange={(e) => setFromId(e.target.value)} required autoFocus>
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

        <FormField label="На счёт">
          <Select value={toId} onChange={(e) => setToId(e.target.value)} required>
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

        <FormField label="Сумма">
          <Input
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            inputMode="decimal"
            placeholder="0"
            required
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
            Перевести
          </Button>
        </div>
      </form>
    </Modal>
  );
}
