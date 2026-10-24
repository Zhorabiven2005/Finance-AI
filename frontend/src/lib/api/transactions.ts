import { api, apiRequestWithTotal } from "@/lib/api/client";
import type { MoneyAmount } from "@/lib/money";

export type TransactionType = "income" | "expense";
export type TransactionSortBy = "occurred_at" | "amount_minor";
export type SortDir = "asc" | "desc";

export interface Transaction {
  id: number;
  account_id: number;
  category_id: number;
  type: TransactionType;
  amount: MoneyAmount;
  occurred_at: string;
  comment: string | null;
  /** Заполнены, если операция — движение денег от погашения долга. */
  debt_id?: number | null;
  debt_name?: string | null;
}

export interface TransactionCreateInput {
  account_id: number;
  category_id: number;
  type: TransactionType;
  amount_minor: number;
  occurred_at: string;
  comment?: string | null;
}

export interface TransactionListParams {
  account_id?: number | undefined;
  category_id?: number | undefined;
  type?: TransactionType | undefined;
  date_from?: string | undefined;
  date_to?: string | undefined;
  amount_min?: number | undefined;
  amount_max?: number | undefined;
  search?: string | undefined;
  sort_by?: TransactionSortBy | undefined;
  sort_dir?: SortDir | undefined;
  limit?: number | undefined;
  offset?: number | undefined;
}

function toQuery(params: TransactionListParams): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") qs.set(key, String(value));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

export const transactionsApi = {
  /** Список операций + общее число подходящих под фильтр (для пагинации),
   * см. заголовок X-Total-Count на backend. */
  list: (params: TransactionListParams = {}) =>
    apiRequestWithTotal<Transaction[]>(`/transactions${toQuery(params)}`),
  create: (input: TransactionCreateInput) => api.post<Transaction>("/transactions", input),
  update: (id: number, input: Partial<TransactionCreateInput>) =>
    api.patch<Transaction>(`/transactions/${id}`, input),
  get: (id: number) => api.get<Transaction>(`/transactions/${id}`),
  remove: (id: number) => api.delete<void>(`/transactions/${id}`),
};
