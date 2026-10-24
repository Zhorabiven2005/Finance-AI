import { api } from "@/lib/api/client";
import type { Account } from "@/lib/api/accounts";
import type { Debt } from "@/lib/api/debts";
import type { Transaction } from "@/lib/api/transactions";
import type { MoneyAmount } from "@/lib/money";

export interface CategorySpending {
  category_id: number;
  category_name: string;
  icon: string | null;
  amount: MoneyAmount;
}

export interface DebtCurrencyTotal {
  currency: string;
  i_owe: MoneyAmount;
  owed_to_me: MoneyAmount;
}

export interface DebtsSummary {
  /** Только базовая валюта (входят в капитал). */
  i_owe_total: MoneyAmount;
  owed_to_me_total: MoneyAmount;
  items: Debt[];
  /** Остатки по каждой валюте отдельно — валюты не складываются. */
  totals_by_currency: DebtCurrencyTotal[];
  overdue_count: number;
}

export interface RecentTransaction extends Transaction {
  account_name: string;
  category_name: string;
  category_icon: string | null;
}

export interface Dashboard {
  net_worth: MoneyAmount;
  accounts: Account[];
  debts: DebtsSummary;
  recent_transactions: RecentTransaction[];
  top_expenses: CategorySpending[];
}

export const dashboardApi = {
  get: () => api.get<Dashboard>("/dashboard"),
};
