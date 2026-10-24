import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { FormField, Input, Select } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { accountsApi, type Account, type AccountType } from "@/lib/api/accounts";
import { errorMessage, FormError } from "@/lib/api/client";
import { systemApi } from "@/lib/api/system";
import { parseToMinor, RUB } from "@/lib/money";

const ACCOUNT_TYPES: { value: AccountType; label: string }[] = [
  { value: "bank", label: "Банковский счёт" },
  { value: "cash", label: "Наличные" },
  { value: "other", label: "Другое" },
];

export function AccountFormModal({
  account,
  onClose,
  onSaved,
}: {
  account: Account | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = account !== null;
  const { data: currencies } = useQuery({
    queryKey: ["currencies"],
    queryFn: systemApi.currencies,
  });

  const [name, setName] = useState(account?.name ?? "");
  const [type, setType] = useState<AccountType>(account?.type ?? "bank");
  const [currency, setCurrency] = useState(account?.currency ?? "RUB");
  const [initialBalance, setInitialBalance] = useState(
    account ? String(account.initial_balance_minor / 100) : "0",
  );
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: async () => {
      if (isEdit) {
        return accountsApi.update(account.id, { name, type });
      }
      const minor = parseToMinor(initialBalance || "0", RUB);
      if (minor === null) throw new FormError("Некорректная сумма начального баланса");
      return accountsApi.create({
        name,
        type,
        currency,
        initial_balance_minor: minor,
      });
    },
    onSuccess: onSaved,
    onError: (err) => setError(errorMessage(err, "Не удалось сохранить счёт")),
  });

  return (
    <Modal title={isEdit ? "Изменить счёт" : "Новый счёт"} onClose={onClose}>
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
            maxLength={100}
            placeholder="Основная карта"
            autoFocus
          />
        </FormField>

        <FormField label="Тип счёта">
          <Select value={type} onChange={(e) => setType(e.target.value as AccountType)}>
            {ACCOUNT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </Select>
        </FormField>

        {!isEdit && (
          <>
            <FormField label="Валюта">
              <Select value={currency} onChange={(e) => setCurrency(e.target.value)}>
                {(currencies ?? [RUB]).map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.code} — {c.name}
                  </option>
                ))}
              </Select>
            </FormField>

            <FormField label="Начальный баланс">
              <Input
                value={initialBalance}
                onChange={(e) => setInitialBalance(e.target.value)}
                inputMode="decimal"
                placeholder="0"
              />
            </FormField>
          </>
        )}

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
