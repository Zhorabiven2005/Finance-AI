import type { BudgetStatus } from "@/lib/api/budgets";

export const BUDGET_STATUS_LABEL: Record<BudgetStatus, string> = {
  ok: "В норме",
  warning: "Близко к лимиту",
  exceeded: "Превышен",
};

export const BUDGET_STATUS_BADGE_TONE: Record<BudgetStatus, "ok" | "warn" | "danger"> = {
  ok: "ok",
  warning: "warn",
  exceeded: "danger",
};

export const BUDGET_STATUS_BAR_CLASS: Record<BudgetStatus, string> = {
  ok: "bg-success",
  warning: "bg-warn",
  exceeded: "bg-danger",
};
