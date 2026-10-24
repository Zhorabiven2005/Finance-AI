import { api } from "@/lib/api/client";
import type { MoneyAmount } from "@/lib/money";

export type AccountType = "bank" | "cash" | "other";

export interface Account {
  id: number;
  name: string;
  type: AccountType;
  currency: string;
  initial_balance_minor: number;
  is_active: boolean;
  balance: MoneyAmount;
}

export interface AccountCreateInput {
  name: string;
  type: AccountType;
  currency: string;
  initial_balance_minor: number;
  is_active?: boolean;
}

export interface AccountUpdateInput {
  name?: string;
  type?: AccountType;
  is_active?: boolean;
}

export const accountsApi = {
  list: (includeInactive = true) =>
    api.get<Account[]>(`/accounts?include_inactive=${includeInactive}`),
  create: (input: AccountCreateInput) => api.post<Account>("/accounts", input),
  update: (id: number, input: AccountUpdateInput) =>
    api.patch<Account>(`/accounts/${id}`, input),
  remove: (id: number) => api.delete<void>(`/accounts/${id}`),
};
