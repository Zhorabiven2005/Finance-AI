import { api } from "@/lib/api/client";
import type { MoneyAmount } from "@/lib/money";

export type BudgetStatus = "ok" | "warning" | "exceeded";

export interface Budget {
  id: number;
  category_id: number;
  category_name: string;
  category_icon: string | null;
  amount: MoneyAmount;
  year: number;
  month: number;
  spent: MoneyAmount;
  remaining: MoneyAmount;
  usage_percent: number;
  status: BudgetStatus;
}

export interface BudgetCreateInput {
  category_id: number;
  amount_minor: number;
  currency: string;
  year: number;
  month: number;
}

export const budgetsApi = {
  list: (year?: number, month?: number) => {
    const qs = new URLSearchParams();
    if (year !== undefined) qs.set("year", String(year));
    if (month !== undefined) qs.set("month", String(month));
    const s = qs.toString();
    return api.get<Budget[]>(`/budgets${s ? `?${s}` : ""}`);
  },
  create: (input: BudgetCreateInput) => api.post<Budget>("/budgets", input),
  update: (id: number, input: { amount_minor: number }) =>
    api.patch<Budget>(`/budgets/${id}`, input),
  remove: (id: number) => api.delete<void>(`/budgets/${id}`),
};
