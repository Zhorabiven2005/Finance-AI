import { api } from "@/lib/api/client";
import type { MoneyAmount } from "@/lib/money";

export interface Transfer {
  id: number;
  from_account_id: number;
  to_account_id: number;
  amount: MoneyAmount;
  occurred_at: string;
  comment: string | null;
}

export interface TransferCreateInput {
  from_account_id: number;
  to_account_id: number;
  amount_minor: number;
  occurred_at: string;
  comment?: string | null;
}

export interface TransferListParams {
  account_id?: number | undefined;
  date_from?: string | undefined;
  date_to?: string | undefined;
}

function toQuery(params: TransferListParams): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") qs.set(key, String(value));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

export const transfersApi = {
  list: (params: TransferListParams = {}) => api.get<Transfer[]>(`/transfers${toQuery(params)}`),
  create: (input: TransferCreateInput) => api.post<Transfer>("/transfers", input),
  remove: (id: number) => api.delete<void>(`/transfers/${id}`),
};
