import { api } from "@/lib/api/client";
import type { MoneyAmount } from "@/lib/money";

export type GoalStatus = "active" | "completed" | "archived";
export type GoalEntryType = "contribution" | "withdrawal";

export interface Goal {
  id: number;
  name: string;
  description: string | null;
  target: MoneyAmount;
  saved: MoneyAmount;
  remaining: MoneyAmount;
  progress_percent: number;
  currency: string;
  target_date: string | null;
  status: GoalStatus;
  created_at: string;
}

export interface GoalCreateInput {
  name: string;
  description?: string | null;
  target_amount_minor: number;
  currency: string;
  target_date?: string | null;
}

export interface GoalUpdateInput {
  name?: string;
  description?: string | null;
  target_amount_minor?: number;
  target_date?: string | null;
  is_archived?: boolean;
}

export interface GoalEntry {
  id: number;
  goal_id: number;
  type: GoalEntryType;
  amount: MoneyAmount;
  occurred_at: string;
  comment: string | null;
}

export interface GoalEntryCreateInput {
  type: GoalEntryType;
  amount_minor: number;
  occurred_at: string;
  comment?: string | null;
}

export const goalsApi = {
  list: (includeArchived = true) =>
    api.get<Goal[]>(`/goals?include_archived=${includeArchived}`),
  get: (id: number) => api.get<Goal>(`/goals/${id}`),
  create: (input: GoalCreateInput) => api.post<Goal>("/goals", input),
  update: (id: number, input: GoalUpdateInput) => api.patch<Goal>(`/goals/${id}`, input),
  remove: (id: number) => api.delete<void>(`/goals/${id}`),
  entries: (goalId: number) => api.get<GoalEntry[]>(`/goals/${goalId}/entries`),
  addEntry: (goalId: number, input: GoalEntryCreateInput) =>
    api.post<GoalEntry>(`/goals/${goalId}/entries`, input),
  removeEntry: (goalId: number, entryId: number) =>
    api.delete<void>(`/goals/${goalId}/entries/${entryId}`),
};
