import { useQuery } from "@tanstack/react-query";
import { HandCoins, X } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, LoadError } from "@/components/ui/Card";
import { ApiError } from "@/lib/api/client";
import type { Category } from "@/lib/api/categories";
import { transactionsApi, type Transaction } from "@/lib/api/transactions";
import { CategoryIcon } from "@/lib/categoryIcons";
import { formatMoney } from "@/lib/money";

import { PURPOSE_EFFECT, PURPOSE_LABEL } from "./TransactionPurposeModal";

/** id операции из ?tx=…: только положительное целое, иначе null —
 * некорректная ссылка не должна приводить к запросу «какой-нибудь» записи. */
export function parseTransactionId(raw: string | null): number | null {
  if (raw === null || !/^\d{1,15}$/.test(raw)) return null;
  const id = Number(raw);
  return id > 0 ? id : null;
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function Shell({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <Card className="border-accent/30">
      <div role="region" aria-label={title}>
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold tracking-tight text-ink-900">{title}</h2>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Закрыть карточку операции">
            <X className="h-4 w-4" strokeWidth={1.75} />
            Закрыть
          </Button>
        </div>
        {children}
      </div>
    </Card>
  );
}

/** Карточка операции, открытой по ссылке /transactions?tx=ID (например, из
 * истории платежей по долгу). Грузится отдельным запросом по id, поэтому не
 * зависит от фильтров, сортировки и страницы журнала и переживает
 * перезагрузку. При ошибке или 404 параметр в адресе не трогается — карточку
 * закрывает сам пользователь. */
export function SelectedTransactionCard({
  rawId,
  accountName,
  categoryOf,
  onEdit,
  onClassify,
  onDelete,
  onClose,
}: {
  rawId: string;
  accountName: (id: number) => string;
  categoryOf: (id: number) => Category | undefined;
  onEdit: (tx: Transaction) => void;
  onClassify: (tx: Transaction) => void;
  onDelete: (tx: Transaction) => void;
  onClose: () => void;
}) {
  const id = parseTransactionId(rawId);
  const { data: tx, isPending, isError, error, isFetching, refetch } = useQuery({
    queryKey: ["transaction", id],
    queryFn: () => transactionsApi.get(id as number),
    enabled: id !== null,
    retry: false,
  });

  if (id === null) {
    return (
      <Shell title="Операция" onClose={onClose}>
        <p role="alert" className="text-[15px] text-ink-500">
          Некорректная ссылка на операцию. Откройте её заново из журнала или карточки долга.
        </p>
      </Shell>
    );
  }
  if (isPending) {
    return (
      <Shell title={`Операция №${id}`} onClose={onClose}>
        <p className="text-[15px] text-ink-500">Загрузка…</p>
      </Shell>
    );
  }
  if (isError || !tx) {
    const notFound = error instanceof ApiError && error.status === 404;
    return (
      <Shell title={`Операция №${id}`} onClose={onClose}>
        {notFound ? (
          <p role="alert" className="text-[15px] text-ink-500">
            Операция №{id} не найдена — возможно, она была удалена.
          </p>
        ) : (
          <LoadError onRetry={() => refetch()} retrying={isFetching}>
            Не удалось загрузить операцию №{id}. Проверьте, что backend запущен.
          </LoadError>
        )}
      </Shell>
    );
  }

  const category = categoryOf(tx.category_id);
  return (
    <Shell title={`Операция №${tx.id}`} onClose={onClose}>
      <div className="flex flex-wrap items-center gap-4" data-testid="selected-transaction">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-hover text-ink-500">
          {tx.debt_id ? (
            <HandCoins className="h-4 w-4" strokeWidth={1.75} />
          ) : (
            category && <CategoryIcon name={category.name} type={category.type} icon={category.icon} />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[15px] font-medium text-ink-900">
            {category?.name ?? "—"}
            <span className="font-normal text-ink-500"> · {accountName(tx.account_id)}</span>
          </p>
          <p className="text-sm text-ink-500">
            {tx.type === "income" ? "Доход" : "Расход"} · {formatDateTime(tx.occurred_at)}
            {tx.comment && <> · {tx.comment}</>}
          </p>
        </div>
        <span
          className={`tabular text-lg font-semibold ${tx.type === "income" ? "text-success" : "text-ink-900"}`}
        >
          {tx.type === "income" ? "+" : "−"}
          {formatMoney(tx.amount)}
        </span>
      </div>

      {tx.debt_id ? (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-page/60 px-4 py-3">
          <p className="flex flex-wrap items-center gap-2 text-sm text-ink-500">
            <Badge tone="neutral">Платёж по долгу</Badge>
            {tx.debt_name && <span className="text-ink-900">«{tx.debt_name}»</span>}
            Изменяется и удаляется только в карточке долга.
          </p>
          <Link to={`/debts/${tx.debt_id}`} className="text-sm font-medium text-accent hover:underline">
            Открыть долг →
          </Link>
        </div>
      ) : (
        <>
        <div className="mt-4 rounded-xl bg-page/60 px-4 py-3 text-sm" data-testid="purpose-info">
          <p className="text-ink-900">
            Назначение: {tx.purpose ? PURPOSE_LABEL[tx.purpose] : tx.type === "income" ? "обычный доход" : "обычный расход"}
            {tx.purpose === "own_transfer" && tx.purpose_account_id ? ` · второй счёт «${accountName(tx.purpose_account_id)}»` : ""}
          </p>
          <p className="text-ink-500">
            {tx.purpose
              ? `${PURPOSE_EFFECT[tx.purpose]} Отметку можно изменить или отменить.`
              : "Если это перевод на свой счёт или договор либо погашение кредитки — отметьте назначение, и операция перестанет считаться обычным расходом."}
          </p>
        </div>
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={() => onClassify(tx)}>
            Назначение
          </Button>
          <Button variant="secondary" size="sm" onClick={() => onEdit(tx)}>
            Изменить
          </Button>
          <Button variant="danger" size="sm" onClick={() => onDelete(tx)}>
            Удалить
          </Button>
        </div>
        </>
      )}
    </Shell>
  );
}
