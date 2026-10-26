import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ArrowLeftRight, ArrowUpDown, HandCoins, Search, X } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";

import { PeriodPicker } from "@/components/PeriodPicker";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader, EmptyState, LoadError } from "@/components/ui/Card";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { Input, Select } from "@/components/ui/Field";
import { accountsApi } from "@/lib/api/accounts";
import { errorMessage } from "@/lib/api/client";
import { categoriesApi, type Category } from "@/lib/api/categories";
import {
  transactionsApi,
  type SortDir,
  type Transaction,
  type TransactionSortBy,
  type TransactionType,
} from "@/lib/api/transactions";
import { transfersApi, type Transfer } from "@/lib/api/transfers";
import { CategoryIcon } from "@/lib/categoryIcons";
import { formatMoney, parseToMinor, RUB } from "@/lib/money";
import { computePeriod, periodToApiParams, type PeriodPreset } from "@/lib/period";
import { useDebouncedValue } from "@/lib/useDebouncedValue";

import { parseTransactionId, SelectedTransactionCard } from "./SelectedTransactionCard";
import { TransactionFormModal } from "./TransactionFormModal";
import { PURPOSE_EFFECT, PURPOSE_LABEL, TransactionPurposeModal } from "./TransactionPurposeModal";
import { TransferFormModal } from "./TransferFormModal";

const PAGE_SIZE = 20;
const OPERATIONS_PRESETS: PeriodPreset[] = [
  "all",
  "today",
  "7d",
  "this_month",
  "last_month",
  "3m",
  "custom",
];

const DEFAULT_SORT = {
  value: "date_desc",
  label: "Дата: сначала новые",
  sortBy: "occurred_at" as TransactionSortBy,
  sortDir: "desc" as SortDir,
};

const SORT_OPTIONS: { value: string; label: string; sortBy: TransactionSortBy; sortDir: SortDir }[] = [
  DEFAULT_SORT,
  { value: "date_asc", label: "Дата: сначала старые", sortBy: "occurred_at", sortDir: "asc" },
  { value: "amount_desc", label: "Сумма: сначала большие", sortBy: "amount_minor", sortDir: "desc" },
  { value: "amount_asc", label: "Сумма: сначала маленькие", sortBy: "amount_minor", sortDir: "asc" },
];

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const DEFAULT_FILTERS = {
  preset: "all" as PeriodPreset,
  customFrom: "",
  customTo: "",
  type: "" as TransactionType | "",
  accountId: "",
  categoryId: "",
  amountMin: "",
  amountMax: "",
  search: "",
  sortKey: "date_desc",
};

type PendingDelete = { kind: "transaction"; item: Transaction } | { kind: "transfer"; item: Transfer };

export function TransactionsPage() {
  const queryClient = useQueryClient();
  // ?tx=ID — открыть конкретную операцию (ссылка из истории платежей по долгу).
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedRaw = searchParams.get("tx");
  const selectedId = parseTransactionId(selectedRaw);
  const closeSelected = () =>
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("tx");
        return next;
      },
      { replace: true },
    );

  const [preset, setPreset] = useState<PeriodPreset>(DEFAULT_FILTERS.preset);
  const [customFrom, setCustomFrom] = useState(DEFAULT_FILTERS.customFrom);
  const [customTo, setCustomTo] = useState(DEFAULT_FILTERS.customTo);
  const [type, setType] = useState<TransactionType | "">(DEFAULT_FILTERS.type);
  const [accountId, setAccountId] = useState(DEFAULT_FILTERS.accountId);
  const [categoryId, setCategoryId] = useState(DEFAULT_FILTERS.categoryId);
  const [amountMin, setAmountMin] = useState(DEFAULT_FILTERS.amountMin);
  const [amountMax, setAmountMax] = useState(DEFAULT_FILTERS.amountMax);
  const [searchInput, setSearchInput] = useState(DEFAULT_FILTERS.search);
  const [sortKey, setSortKey] = useState(DEFAULT_FILTERS.sortKey);
  const [page, setPage] = useState(1);

  const [formType, setFormType] = useState<TransactionType | null>(null);
  const [transferOpen, setTransferOpen] = useState(false);
  const [editing, setEditing] = useState<Transaction | null>(null);
  // Операция, для которой открыт выбор назначения (Stage 3F).
  const [classifying, setClassifying] = useState<Transaction | null>(null);
  const [deleting, setDeleting] = useState<PendingDelete | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const search = useDebouncedValue(searchInput, 300);
  const sort = SORT_OPTIONS.find((o) => o.value === sortKey) ?? DEFAULT_SORT;
  const period = computePeriod(preset, { from: customFrom, to: customTo });
  const periodParams = period ? periodToApiParams(period) : { date_from: undefined, date_to: undefined };

  const amountMinMinor = amountMin ? parseToMinor(amountMin, RUB) ?? undefined : undefined;
  const amountMaxMinor = amountMax ? parseToMinor(amountMax, RUB) ?? undefined : undefined;

  const isDefaultFilters =
    preset === DEFAULT_FILTERS.preset &&
    type === DEFAULT_FILTERS.type &&
    accountId === DEFAULT_FILTERS.accountId &&
    categoryId === DEFAULT_FILTERS.categoryId &&
    amountMin === DEFAULT_FILTERS.amountMin &&
    amountMax === DEFAULT_FILTERS.amountMax &&
    searchInput === DEFAULT_FILTERS.search &&
    sortKey === DEFAULT_FILTERS.sortKey;

  // Смена любого фильтра (кроме страницы) возвращает на первую страницу —
  // иначе легко оказаться на "странице 5", которая после фильтра пуста.
  const filtersSignature = JSON.stringify([
    preset,
    customFrom,
    customTo,
    type,
    accountId,
    categoryId,
    amountMinMinor,
    amountMaxMinor,
    search,
    sortKey,
  ]);
  useEffect(() => {
    setPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtersSignature]);

  const { data: accounts } = useQuery({ queryKey: ["accounts"], queryFn: () => accountsApi.list(true) });
  // С архивными: у исторической операции категория должна оставаться видна,
  // даже если её потом архивировали.
  const { data: allCategories } = useQuery({
    queryKey: ["categories", "all-including-archived"],
    queryFn: () => categoriesApi.list({ includeArchived: true }),
  });

  const listParams = {
    account_id: accountId ? Number(accountId) : undefined,
    category_id: categoryId ? Number(categoryId) : undefined,
    type: type || undefined,
    date_from: periodParams.date_from,
    date_to: periodParams.date_to,
    amount_min: amountMinMinor,
    amount_max: amountMaxMinor,
    search: search || undefined,
    sort_by: sort.sortBy,
    sort_dir: sort.sortDir,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  };

  const {
    data: txResult,
    isPending: txPending,
    isError: txError,
    isFetching: txFetching,
    refetch: refetchTx,
  } = useQuery({
    queryKey: ["transactions", listParams],
    queryFn: () => transactionsApi.list(listParams),
  });
  const transactions = txResult?.data ?? [];
  const total = txResult?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // Переводы — отдельная сущность (не доход/расход, без категории), их не
  // проводят через сортировку/поиск/пагинацию операций: показываются
  // отдельным лёгким блоком за тот же период и счёт.
  const showTransfers = !type && !categoryId && !search;
  const { data: transfers } = useQuery({
    queryKey: ["transfers", accountId, periodParams.date_from, periodParams.date_to, showTransfers],
    queryFn: () =>
      transfersApi.list({
        account_id: accountId ? Number(accountId) : undefined,
        date_from: periodParams.date_from,
        date_to: periodParams.date_to,
      }),
    enabled: showTransfers,
  });

  const accountName = (id: number) => accounts?.find((a) => a.id === id)?.name ?? `#${id}`;
  const categoryOf = (id: number) => allCategories?.find((c) => c.id === id);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["transactions"] });
    queryClient.invalidateQueries({ queryKey: ["transaction"] });
    queryClient.invalidateQueries({ queryKey: ["transfers"] });
    queryClient.invalidateQueries({ queryKey: ["accounts"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    queryClient.invalidateQueries({ queryKey: ["analytics"] });
    queryClient.invalidateQueries({ queryKey: ["budgets"] });
    // Назначение и правки операций меняют инсайты, сравнение и предупреждения.
    queryClient.invalidateQueries({ queryKey: ["insights"] });
    queryClient.invalidateQueries({ queryKey: ["insights-warnings"] });
    queryClient.invalidateQueries({ queryKey: ["context"] });
  };

  const remove = useMutation({
    mutationFn: (target: PendingDelete) =>
      target.kind === "transaction"
        ? transactionsApi.remove(target.item.id)
        : transfersApi.remove(target.item.id),
    onSuccess: (_, target) => {
      setDeleting(null);
      // Выбранную операцию, которую пользователь сам удалил, закрываем сразу,
      // а не показываем «не найдена» на только что удалённую запись.
      if (target.kind === "transaction" && target.item.id === selectedId) {
        queryClient.removeQueries({ queryKey: ["transaction", target.item.id] });
        closeSelected();
      }
      invalidate();
    },
    onError: (err, target) =>
      setDeleteError(
        errorMessage(
          err,
          target.kind === "transaction" ? "Не удалось удалить операцию" : "Не удалось удалить перевод",
        ),
      ),
  });
  const askDelete = (target: PendingDelete) => {
    setDeleteError(null);
    setDeleting(target);
  };
  const openEdit = (tx: Transaction) => {
    setEditing(tx);
    setFormType(tx.type);
  };

  const resetFilters = () => {
    setPreset(DEFAULT_FILTERS.preset);
    setCustomFrom(DEFAULT_FILTERS.customFrom);
    setCustomTo(DEFAULT_FILTERS.customTo);
    setType(DEFAULT_FILTERS.type);
    setAccountId(DEFAULT_FILTERS.accountId);
    setCategoryId(DEFAULT_FILTERS.categoryId);
    setAmountMin(DEFAULT_FILTERS.amountMin);
    setAmountMax(DEFAULT_FILTERS.amountMax);
    setSearchInput(DEFAULT_FILTERS.search);
    setSortKey(DEFAULT_FILTERS.sortKey);
  };

  const incomeCategories = (allCategories ?? []).filter((c: Category) => c.type === "income");
  const expenseCategories = (allCategories ?? []).filter((c: Category) => c.type === "expense");
  const categoryOptions =
    type === "income" ? incomeCategories : type === "expense" ? expenseCategories : null;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-[28px] font-semibold tracking-tight text-ink-900">Операции</h1>
        <div className="flex flex-wrap gap-3">
          <Button
            variant="secondary"
            onClick={() => {
              setEditing(null);
              setFormType("income");
            }}
          >
            + Доход
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              setEditing(null);
              setFormType("expense");
            }}
          >
            + Расход
          </Button>
          <Button variant="secondary" onClick={() => setTransferOpen(true)}>
            + Перевод
          </Button>
        </div>
      </div>

      {selectedRaw !== null && (
        <SelectedTransactionCard
          rawId={selectedRaw}
          accountName={accountName}
          categoryOf={categoryOf}
          onEdit={openEdit}
          onClassify={setClassifying}
          onDelete={(tx) => askDelete({ kind: "transaction", item: tx })}
          onClose={closeSelected}
        />
      )}

      <Card>
        <div className="flex flex-col gap-4">
          <PeriodPicker
            preset={preset}
            onPresetChange={setPreset}
            customFrom={customFrom}
            customTo={customTo}
            onCustomChange={(from, to) => {
              setCustomFrom(from);
              setCustomTo(to);
            }}
            presets={OPERATIONS_PRESETS}
          />

          <div className="flex flex-wrap items-end gap-3">
            <div className="relative min-w-[220px] flex-1">
              <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" strokeWidth={1.75} />
              <Input
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="Поиск по комментарию, категории, счёту"
                className="pl-10"
              />
            </div>

            <Select
              value={type}
              onChange={(e) => {
                setType(e.target.value as TransactionType | "");
                setCategoryId("");
              }}
              className="w-40"
            >
              <option value="">Все типы</option>
              <option value="income">Доход</option>
              <option value="expense">Расход</option>
            </Select>

            <Select value={accountId} onChange={(e) => setAccountId(e.target.value)} className="w-44">
              <option value="">Все счета</option>
              {(accounts ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>

            <Select value={categoryId} onChange={(e) => setCategoryId(e.target.value)} className="w-48">
              <option value="">Все категории</option>
              {categoryOptions ? (
                categoryOptions.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))
              ) : (
                <>
                  <optgroup label="Доходы">
                    {incomeCategories.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </optgroup>
                  <optgroup label="Расходы">
                    {expenseCategories.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </optgroup>
                </>
              )}
            </Select>

            <Input
              value={amountMin}
              onChange={(e) => setAmountMin(e.target.value)}
              placeholder="Сумма от"
              inputMode="decimal"
              className="w-28"
            />
            <Input
              value={amountMax}
              onChange={(e) => setAmountMax(e.target.value)}
              placeholder="до"
              inputMode="decimal"
              className="w-28"
            />

            <Select
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value)}
              className="w-56"
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>

            {!isDefaultFilters && (
              <Button variant="ghost" size="sm" onClick={resetFilters}>
                <X className="h-4 w-4" strokeWidth={1.75} />
                Сбросить фильтры
              </Button>
            )}
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader
          title="История"
          action={
            !txPending && (
              <span className="text-sm text-ink-500">
                {total === 0 ? "Ничего не найдено" : `Найдено: ${total}`}
              </span>
            )
          }
        />
        {txPending ? (
          <p className="text-[15px] text-ink-500">Загрузка…</p>
        ) : txError ? (
          <LoadError onRetry={() => refetchTx()} retrying={txFetching} />
        ) : transactions.length === 0 ? (
          <EmptyState>
            {isDefaultFilters
              ? "Операций пока нет."
              : "Ничего не подходит под текущие фильтры."}
          </EmptyState>
        ) : (
          <ul className="divide-y divide-border">
            {transactions.map((tx) => {
              const category = categoryOf(tx.category_id);
              return (
                <li
                  key={tx.id}
                  data-testid="transaction-row"
                  aria-current={tx.id === selectedId ? "true" : undefined}
                  className={`flex items-center gap-4 py-4 first:pt-0 last:pb-0 ${
                    tx.id === selectedId ? "-mx-3 rounded-xl bg-accent-soft px-3 first:pt-4 last:pb-4" : ""
                  }`}
                >
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-hover text-ink-500">
                    {tx.debt_id ? (
                      <HandCoins className="h-4 w-4" strokeWidth={1.75} />
                    ) : category ? (
                      <CategoryIcon name={category.name} type={category.type} icon={category.icon} />
                    ) : (
                      <ArrowUpDown className="h-4 w-4" strokeWidth={1.75} />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[15px] font-medium text-ink-900">
                      {category?.name ?? "—"}
                      <span className="font-normal text-ink-500"> · {accountName(tx.account_id)}</span>
                      {tx.comment && <span className="font-normal text-ink-500"> · {tx.comment}</span>}
                    </p>
                    <p className="text-sm text-ink-500">
                      {tx.debt_name && <>Долг: {tx.debt_name} · </>}
                      {formatDateTime(tx.occurred_at)}
                    </p>
                    {tx.purpose && (
                      <p className="mt-1" data-testid="purpose-badge">
                        <Badge tone="neutral">{PURPOSE_LABEL[tx.purpose]}</Badge>
                        <span className="ml-2 text-xs text-ink-400">{PURPOSE_EFFECT[tx.purpose]}</span>
                      </p>
                    )}
                  </div>
                  <span
                    className={`tabular text-[15px] font-semibold ${tx.type === "income" ? "text-success" : "text-ink-900"}`}
                  >
                    {tx.type === "income" ? "+" : "−"}
                    {formatMoney(tx.amount)}
                  </span>
                  {tx.debt_id ? (
                    // Операция принадлежит платежу по долгу: правится и
                    // удаляется там, иначе долг и счёт разойдутся.
                    <Link
                      to={`/debts/${tx.debt_id}`}
                      className="whitespace-nowrap text-right text-sm font-medium text-accent hover:underline"
                    >
                      Платёж в «Долгах» →
                    </Link>
                  ) : (
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      <Button variant="ghost" size="sm" onClick={() => setClassifying(tx)}>
                        Назначение
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => openEdit(tx)}
                      >
                        Изменить
                      </Button>
                      <Button
                        variant="danger"
                        size="sm"
                        onClick={() => askDelete({ kind: "transaction", item: tx })}
                      >
                        Удалить
                      </Button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        {total > PAGE_SIZE && (
          <div className="mt-5 flex items-center justify-between border-t border-border pt-4">
            <p className="text-sm text-ink-500">
              Страница {page} из {totalPages}
            </p>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Назад
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              >
                Вперёд
              </Button>
            </div>
          </div>
        )}
      </Card>

      {showTransfers && (transfers?.length ?? 0) > 0 && (
        <Card>
          <CardHeader title="Переводы" />
          <ul className="divide-y divide-border">
            {(transfers as Transfer[]).map((tr) => (
              <li key={tr.id} className="flex items-center gap-4 py-4 first:pt-0 last:pb-0">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-hover text-ink-500">
                  <ArrowLeftRight className="h-4 w-4" strokeWidth={1.75} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[15px] font-medium text-ink-900">
                    {accountName(tr.from_account_id)} → {accountName(tr.to_account_id)}
                    {tr.comment && <span className="font-normal text-ink-500"> · {tr.comment}</span>}
                  </p>
                  <p className="text-sm text-ink-500">{formatDateTime(tr.occurred_at)}</p>
                </div>
                <span className="tabular text-[15px] font-semibold text-ink-500">
                  {formatMoney(tr.amount)}
                </span>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => askDelete({ kind: "transfer", item: tr })}
                >
                  Удалить
                </Button>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {deleting && (
        <ConfirmModal
          title={deleting.kind === "transaction" ? "Удалить операцию?" : "Удалить перевод?"}
          pending={remove.isPending}
          error={deleteError}
          onConfirm={() => remove.mutate(deleting)}
          onClose={() => setDeleting(null)}
        >
          {deleting.kind === "transaction" ? (
            <p>
              {deleting.item.type === "income" ? "Доход" : "Расход"} {formatMoney(deleting.item.amount)} от{" "}
              {formatDateTime(deleting.item.occurred_at)} будет удалён, баланс счёта «
              {accountName(deleting.item.account_id)}» пересчитается.
            </p>
          ) : (
            <p>
              Перевод {formatMoney(deleting.item.amount)} «{accountName(deleting.item.from_account_id)}» → «
              {accountName(deleting.item.to_account_id)}» будет удалён, балансы обоих счетов пересчитаются.
            </p>
          )}
        </ConfirmModal>
      )}
      {formType && (
        <TransactionFormModal
          type={formType}
          transaction={editing}
          onClose={() => {
            setFormType(null);
            setEditing(null);
          }}
          onSaved={() => {
            setFormType(null);
            setEditing(null);
            invalidate();
          }}
        />
      )}
      {classifying && (
        <TransactionPurposeModal
          tx={classifying}
          accounts={accounts ?? []}
          accountName={accountName}
          onClose={() => setClassifying(null)}
          onSaved={invalidate}
        />
      )}
      {transferOpen && (
        <TransferFormModal
          onClose={() => setTransferOpen(false)}
          onSaved={() => {
            setTransferOpen(false);
            invalidate();
          }}
        />
      )}
    </div>
  );
}
