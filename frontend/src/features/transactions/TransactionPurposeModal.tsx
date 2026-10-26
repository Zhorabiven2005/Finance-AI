import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { FieldError, FormField, Select } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import type { Account } from "@/lib/api/accounts";
import { errorMessage } from "@/lib/api/client";
import { debtsApi } from "@/lib/api/debts";
import { transactionsApi, type Transaction, type TransactionPurpose } from "@/lib/api/transactions";
import { cn } from "@/lib/cn";
import { formatMoney } from "@/lib/money";

/** Ручная классификация операции (Stage 3F). Выбор делает только
 * пользователь; сумма, дата, счёт, категория и описание не меняются, остаток
 * счёта тоже — меняется только учёт в доходах и расходах. */

type Choice = "regular" | TransactionPurpose;

export const PURPOSE_LABEL: Record<TransactionPurpose, string> = {
  own_transfer: "Перевод между своими счетами",
  external_transfer: "Перевод на свой внешний продукт",
  debt_repayment: "Погашение долга или кредитки",
};

/** Как назначение влияет на показатели — одна строка для бейджа и карточки. */
export const PURPOSE_EFFECT: Record<TransactionPurpose, string> = {
  own_transfer: "Не считается ни доходом, ни расходом.",
  external_transfer: "Не считается ни доходом, ни расходом: деньги остаются вашими.",
  debt_repayment: "Не входит в расходы на жизнь; учитывается в денежном потоке как погашение.",
};

function options(type: Transaction["type"]): { value: Choice; title: string; effect: string }[] {
  const regular =
    type === "expense"
      ? { value: "regular" as const, title: "Обычный расход", effect: "Покупка или услуга — входит в расходы." }
      : { value: "regular" as const, title: "Обычный доход", effect: "Входит в доходы." };
  const list: { value: Choice; title: string; effect: string }[] = [
    regular,
    {
      value: "own_transfer",
      title: PURPOSE_LABEL.own_transfer,
      effect: `${PURPOSE_EFFECT.own_transfer} Укажите второй свой счёт.`,
    },
    {
      value: "external_transfer",
      title: type === "expense" ? "Перевод на свой внешний продукт" : "Перевод со своего внешнего продукта",
      effect: `Свой счёт или договор, которого нет в приложении (вклад, кредитка в другом банке). ${PURPOSE_EFFECT.external_transfer}`,
    },
  ];
  if (type === "expense") {
    list.push({
      value: "debt_repayment",
      title: PURPOSE_LABEL.debt_repayment,
      effect: `${PURPOSE_EFFECT.debt_repayment} Если сами покупки по кредитке в приложении не записаны, расходы на жизнь будут занижены.`,
    });
  }
  return list;
}

export function TransactionPurposeModal({
  tx,
  accounts,
  accountName,
  onClose,
  onSaved,
}: {
  tx: Transaction;
  accounts: Account[];
  accountName: (id: number) => string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const queryClient = useQueryClient();
  const [choice, setChoice] = useState<Choice>(tx.purpose ?? "regular");
  const [accountId, setAccountId] = useState<string>(tx.purpose_account_id ? String(tx.purpose_account_id) : "");
  const [debtId, setDebtId] = useState<string>(tx.purpose_debt_id ? String(tx.purpose_debt_id) : "");
  const [pairId, setPairId] = useState<number | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);

  const otherAccounts = accounts.filter((a) => a.id !== tx.account_id && a.currency === tx.amount.currency);
  const debts = useQuery({ queryKey: ["debts"], queryFn: debtsApi.list, enabled: choice === "debt_repayment" });
  const myDebts = (debts.data ?? []).filter(
    (d) => d.direction === "i_owe" && d.principal.currency === tx.amount.currency,
  );
  const candidates = useQuery({
    queryKey: ["transaction-pair-candidates", tx.id],
    queryFn: () => transactionsApi.pairCandidates(tx.id),
    enabled: choice === "own_transfer",
  });

  const save = useMutation({
    mutationFn: async () => {
      const purpose = choice === "regular" ? null : choice;
      const saved = await transactionsApi.setPurpose(tx.id, {
        purpose,
        purpose_account_id: purpose === "own_transfer" ? Number(accountId) : null,
        purpose_debt_id: purpose === "debt_repayment" && debtId ? Number(debtId) : null,
      });
      // Вторая сторона перевода — только если пользователь сам её отметил.
      if (purpose === "own_transfer" && pairId !== null) {
        await transactionsApi.setPurpose(pairId, { purpose: "own_transfer", purpose_account_id: tx.account_id });
      }
      return saved;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transaction-pair-candidates"] });
      onSaved();
      onClose();
    },
  });

  const submit = () => {
    if (choice === "own_transfer" && !accountId) {
      setFieldError("Выберите второй свой счёт, участвующий в переводе.");
      return;
    }
    setFieldError(null);
    save.mutate();
  };

  const pickCandidate = (c: Transaction) => {
    setPairId((current) => (current === c.id ? null : c.id));
    if (!accountId) setAccountId(String(c.account_id));
  };

  return (
    <Modal title="Назначение операции" onClose={onClose} size="lg">
      <div className="flex flex-col gap-5">
        <p className="text-sm text-ink-500">
          {tx.type === "income" ? "Доход" : "Расход"} {formatMoney(tx.amount)} · {accountName(tx.account_id)} ·{" "}
          {new Date(tx.occurred_at).toLocaleDateString("ru-RU")}
          {tx.comment ? ` · ${tx.comment}` : ""}
        </p>

        <fieldset className="flex flex-col gap-2" aria-label="Назначение">
          {options(tx.type).map((o) => (
            <label
              key={o.value}
              className={cn(
                "flex cursor-pointer items-start gap-3 rounded-xl border p-3",
                choice === o.value ? "border-accent bg-accent-soft/40" : "border-border",
              )}
            >
              <input
                type="radio"
                name="purpose"
                value={o.value}
                checked={choice === o.value}
                onChange={() => setChoice(o.value)}
                className="mt-1"
              />
              <span className="min-w-0">
                <span className="block text-[15px] font-medium text-ink-900">{o.title}</span>
                <span className="block text-sm text-ink-500">{o.effect}</span>
              </span>
            </label>
          ))}
        </fieldset>

        {choice === "own_transfer" && (
          <div className="flex flex-col gap-3">
            <FormField label="Второй свой счёт" htmlFor="purpose-account">
              <Select id="purpose-account" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
                <option value="">— выберите счёт —</option>
                {otherAccounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </Select>
            </FormField>
            {otherAccounts.length === 0 && (
              <p className="text-sm text-ink-500">
                Другого счёта в той же валюте нет. Если деньги ушли на счёт вне приложения, выберите «Перевод на свой
                внешний продукт».
              </p>
            )}
            {(candidates.data ?? []).length > 0 && (
              <div className="rounded-xl bg-page px-3 py-3" data-testid="pair-candidates">
                <p className="text-sm font-medium text-ink-900">Возможная вторая сторона перевода</p>
                <p className="mb-2 text-sm text-ink-500">
                  Та же сумма в течение суток на другом счёте. Приложение не связывает операции само — отметьте, если
                  это действительно ваш перевод.
                </p>
                {candidates.data!.map((c) => (
                  <label key={c.id} className="flex cursor-pointer items-start gap-2 py-1 text-sm text-ink-700">
                    <input type="checkbox" checked={pairId === c.id} onChange={() => pickCandidate(c)} className="mt-1" />
                    <span>
                      Отметить и её как перевод: {c.type === "income" ? "+" : "−"}
                      {formatMoney(c.amount)} · {accountName(c.account_id)} ·{" "}
                      {new Date(c.occurred_at).toLocaleString("ru-RU")}
                      {c.comment ? ` · ${c.comment}` : ""}
                    </span>
                  </label>
                ))}
              </div>
            )}
          </div>
        )}

        {choice === "debt_repayment" && (
          <FormField label="Какой долг погашает (необязательно)" htmlFor="purpose-debt">
            <Select id="purpose-debt" value={debtId} onChange={(e) => setDebtId(e.target.value)}>
              <option value="">— не указывать —</option>
              {myDebts.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.counterparty_name}
                </option>
              ))}
            </Select>
            <p className="mt-2 text-sm text-ink-500">
              Ссылка на долг только для справки: остаток долга меняется платежом в разделе «Долги».
            </p>
          </FormField>
        )}

        <p className="text-sm text-ink-400">
          Сумма, дата, счёт, категория и описание операции не меняются, остаток счёта тоже. Выбор можно изменить или
          отменить в любой момент.
        </p>

        <FieldError>{fieldError ?? (save.isError ? errorMessage(save.error) : undefined)}</FieldError>

        <div className="flex flex-wrap justify-end gap-3">
          <Button variant="secondary" onClick={onClose}>
            Отмена
          </Button>
          <Button onClick={submit} disabled={save.isPending} aria-busy={save.isPending}>
            Сохранить
          </Button>
        </div>
      </div>
    </Modal>
  );
}
