import { api } from "@/lib/api/client";
import type { MoneyAmount } from "@/lib/money";

export type RecurringType = "income" | "expense";
export type Frequency = "daily" | "weekly" | "monthly" | "yearly";

export interface RecurringTransaction {
  id: number;
  type: RecurringType;
  account_id: number;
  account_name: string;
  category_id: number;
  category_name: string;
  category_icon: string | null;
  amount: MoneyAmount;
  comment: string | null;
  start_date: string;
  end_date: string | null;
  frequency: Frequency;
  next_run_date: string;
  is_active: boolean;
}

export interface RecurringTransactionCreateInput {
  type: RecurringType;
  account_id: number;
  category_id: number;
  amount_minor: number;
  comment?: string | null;
  start_date: string;
  end_date?: string | null;
  frequency: Frequency;
  next_run_date?: string | null;
}

export interface RecurringTransactionUpdateInput {
  account_id?: number;
  category_id?: number;
  amount_minor?: number;
  comment?: string | null;
  end_date?: string | null;
  is_active?: boolean;
}

export interface RecurringProcessResult {
  created_transactions: number;
  deactivated_rules: number;
}

export const recurringTransactionsApi = {
  list: (isActive?: boolean) =>
    api.get<RecurringTransaction[]>(
      isActive === undefined ? "/recurring-transactions" : `/recurring-transactions?is_active=${isActive}`,
    ),
  create: (input: RecurringTransactionCreateInput) =>
    api.post<RecurringTransaction>("/recurring-transactions", input),
  update: (id: number, input: RecurringTransactionUpdateInput) =>
    api.patch<RecurringTransaction>(`/recurring-transactions/${id}`, input),
  remove: (id: number) => api.delete<void>(`/recurring-transactions/${id}`),
  process: (asOf?: string) =>
    api.post<RecurringProcessResult>(
      `/recurring-transactions/process${asOf ? `?as_of=${asOf}` : ""}`,
      undefined,
    ),
};
