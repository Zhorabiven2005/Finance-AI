import { api } from "@/lib/api/client";
import type { MoneyAmount } from "@/lib/money";

export type Granularity = "day" | "week" | "month";

export interface AnalyticsSummary {
  income: MoneyAmount;
  expense: MoneyAmount;
  balance: MoneyAmount;
  transaction_count: number;
}

export interface PeriodComparison {
  has_previous_data: boolean;
  previous_income: MoneyAmount;
  previous_expense: MoneyAmount;
  income_change_percent: number | null;
  expense_change_percent: number | null;
}

export interface TimeseriesPoint {
  period_start: string;
  income: MoneyAmount;
  expense: MoneyAmount;
}

export interface CategoryBreakdownItem {
  category_id: number;
  category_name: string;
  category_icon?: string | null;
  amount: MoneyAmount;
  percent: number;
}

export interface TopExpenseItem {
  transaction_id: number;
  amount: MoneyAmount;
  category_name: string;
  category_icon?: string | null;
  account_name: string;
  occurred_at: string;
  comment: string | null;
}

export interface Analytics {
  date_from: string;
  date_to: string;
  currency: string;
  granularity: Granularity;
  summary: AnalyticsSummary;
  comparison: PeriodComparison;
  timeseries: TimeseriesPoint[];
  category_breakdown: CategoryBreakdownItem[];
  top_expenses: TopExpenseItem[];
}

export const analyticsApi = {
  get: (dateFrom: string, dateTo: string) =>
    api.get<Analytics>(`/analytics?date_from=${encodeURIComponent(dateFrom)}&date_to=${encodeURIComponent(dateTo)}`),
};
