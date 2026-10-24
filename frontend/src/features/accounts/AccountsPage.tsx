import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { AccountTypeIcon } from "@/lib/accountIcons";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader, EmptyState, LoadError } from "@/components/ui/Card";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { accountsApi, type Account, type AccountType } from "@/lib/api/accounts";
import { errorMessage } from "@/lib/api/client";
import { formatMoney } from "@/lib/money";

import { AccountFormModal } from "./AccountFormModal";

const ACCOUNT_TYPE_LABEL: Record<AccountType, string> = {
  bank: "Банковский счёт",
  cash: "Наличные",
  other: "Другое",
};

export function AccountsPage() {
  const queryClient = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Account | null>(null);
  const [deleting, setDeleting] = useState<Account | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ title: string; text: string } | null>(null);

  const { data: accounts, isPending, isError, isFetching, refetch } = useQuery({
    queryKey: ["accounts"],
    queryFn: () => accountsApi.list(true),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["accounts"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  };

  const toggleActive = useMutation({
    mutationFn: (account: Account) =>
      accountsApi.update(account.id, { is_active: !account.is_active }),
    onSuccess: invalidate,
    onError: (err) => setNotice({ title: "Не удалось изменить счёт", text: errorMessage(err) }),
  });

  const remove = useMutation({
    mutationFn: (account: Account) => accountsApi.remove(account.id),
    onSuccess: () => {
      setDeleting(null);
      invalidate();
    },
    onError: (err) => setDeleteError(errorMessage(err, "Не удалось удалить счёт")),
  });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-[28px] font-semibold tracking-tight text-ink-900">Счета</h1>
        <Button
          onClick={() => {
            setEditing(null);
            setModalOpen(true);
          }}
        >
          + Новый счёт
        </Button>
      </div>

      <Card>
        <CardHeader title="Все счета" />
        {isPending ? (
          <p className="text-[15px] text-ink-500">Загрузка…</p>
        ) : isError ? (
          <LoadError onRetry={() => refetch()} retrying={isFetching} />
        ) : !accounts || accounts.length === 0 ? (
          <EmptyState>Счетов пока нет — создайте первый.</EmptyState>
        ) : (
          <ul className="divide-y divide-border">
            {accounts.map((a) => (
              <li key={a.id} className="flex items-center gap-4 py-4 first:pt-0 last:pb-0">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-hover text-ink-500">
                  <AccountTypeIcon type={a.type} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="truncate text-[17px] font-medium text-ink-900">{a.name}</p>
                    {!a.is_active && <Badge tone="neutral">Неактивен</Badge>}
                  </div>
                  <p className="text-sm text-ink-500">
                    {ACCOUNT_TYPE_LABEL[a.type]} · {a.currency}
                  </p>
                </div>
                <span
                  className={`tabular text-lg font-semibold ${a.balance.minor < 0 ? "text-danger" : "text-ink-900"}`}
                >
                  {formatMoney(a.balance)}
                </span>
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setEditing(a);
                      setModalOpen(true);
                    }}
                  >
                    Изменить
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={toggleActive.isPending && toggleActive.variables?.id === a.id}
                    onClick={() => toggleActive.mutate(a)}
                  >
                    {a.is_active ? "Деактивировать" : "Активировать"}
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={() => {
                      setDeleteError(null);
                      setDeleting(a);
                    }}
                  >
                    Удалить
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {deleting && (
        <ConfirmModal
          title={`Удалить счёт «${deleting.name}»?`}
          pending={remove.isPending}
          error={deleteError}
          onConfirm={() => remove.mutate(deleting)}
          onClose={() => setDeleting(null)}
        >
          <p>
            Удалить можно только счёт без операций, переводов и связанных данных. Если по счёту уже есть
            история, деактивируйте его: он исчезнет из выбора в формах, а история сохранится.
          </p>
        </ConfirmModal>
      )}
      {notice && (
        <ConfirmModal title={notice.title} onClose={() => setNotice(null)}>
          {notice.text}
        </ConfirmModal>
      )}
      {modalOpen && (
        <AccountFormModal
          account={editing}
          onClose={() => setModalOpen(false)}
          onSaved={() => {
            setModalOpen(false);
            invalidate();
          }}
        />
      )}
    </div>
  );
}
