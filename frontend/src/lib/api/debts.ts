import { api } from "@/lib/api/client";
import type { MoneyAmount } from "@/lib/money";

export type DebtDirection = "i_owe" | "owed_to_me";
export type DebtStatus = "active" | "partially_paid" | "paid";
export type DebtDueState = "none" | "upcoming" | "soon" | "today" | "overdue" | "paid";

export interface Debt {
  id: number;
  counterparty_name: string;
  direction: DebtDirection;
  principal: MoneyAmount;
  paid: MoneyAmount;
  remaining: MoneyAmount;
  status: DebtStatus;
  due_date: string | null;
  comment: string | null;
  /** Вычисляется на backend: процент погашения 0–100. */
  paid_percent: number;
  due_state: DebtDueState;
  days_until_due: number | null;
  created_at: string | null;
}

export interface DebtUpdateInput {
  counterparty_name?: string;
  due_date?: string | null;
  comment?: string | null;
}

export interface DebtCreateInput {
  counterparty_name: string;
  direction: DebtDirection;
  principal_minor: number;
  currency: string;
  due_date?: string | null;
  comment?: string | null;
}

export interface DebtPayment {
  id: number;
  debt_id: number;
  account_id: number | null;
  transaction_id: number | null;
  amount: MoneyAmount;
  paid_at: string;
  comment: string | null;
}

export interface DebtPaymentCreateInput {
  amount_minor: number;
  paid_at: string;
  account_id?: number | null;
  comment?: string | null;
}

export interface DebtPaymentUpdateInput {
  amount_minor?: number;
  paid_at?: string;
  account_id?: number | null;
  comment?: string | null;
}

export const debtsApi = {
  list: () => api.get<Debt[]>("/debts"),
  get: (id: number) => api.get<Debt>(`/debts/${id}`),
  update: (id: number, input: DebtUpdateInput) => api.patch<Debt>(`/debts/${id}`, input),
  create: (input: DebtCreateInput) => api.post<Debt>("/debts", input),
  remove: (id: number) => api.delete<void>(`/debts/${id}`),
  payments: (debtId: number) => api.get<DebtPayment[]>(`/debts/${debtId}/payments`),
  addPayment: (debtId: number, input: DebtPaymentCreateInput) =>
    api.post<DebtPayment>(`/debts/${debtId}/payments`, input),
  updatePayment: (debtId: number, paymentId: number, input: DebtPaymentUpdateInput) =>
    api.patch<DebtPayment>(`/debts/${debtId}/payments/${paymentId}`, input),
  removePayment: (debtId: number, paymentId: number) =>
    api.delete<void>(`/debts/${debtId}/payments/${paymentId}`),
};
