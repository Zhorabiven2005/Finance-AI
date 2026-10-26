import { postNdjson, type StreamEvent } from "@/lib/api/assistant";
import { api } from "@/lib/api/client";
import type { MoneyAmount } from "@/lib/money";

/** Финансовые инсайты (Stage 3C): все числа посчитаны backend. */

export type InsightType =
  | "cash_flow"
  | "spending_structure"
  | "large_expenses"
  | "recurring_expenses"
  | "budgets"
  | "goals"
  | "data_quality";
export type InsightPeriodKey = "current_month" | "previous_month" | "last_3_months";

export interface InsightPeriod {
  key: InsightPeriodKey | "today";
  date_from: string;
  date_to: string;
  label: string;
  complete: boolean;
}

export interface InsightMetric {
  label: string;
  money?: MoneyAmount | null;
  percent?: number | null;
  count?: number | null;
}

export interface InsightItem {
  label: string;
  money?: MoneyAmount | null;
  percent?: number | null;
  date?: string | null;
  note?: string | null;
}

export interface Insight {
  id: string;
  type: InsightType;
  title: string;
  severity: "info" | "attention" | "warning";
  confidence: "high" | "medium" | "low";
  period: InsightPeriod;
  currency: string | null;
  metrics: InsightMetric[];
  items: InsightItem[];
  summary: string;
  limitations: string[];
  link: { to: string; label: string } | null;
}

export interface UnavailableInsight {
  type: InsightType;
  currency: string | null;
  kind: "insufficient_data" | "nothing_found" | "not_applicable";
  reason: string;
}

export interface InsightsResponse {
  generated_at: string;
  today: string;
  period: InsightPeriod;
  currencies: string[];
  insights: Insight[];
  unavailable: UnavailableInsight[];
}

export const insightsApi = {
  get: (period: InsightPeriodKey) => api.get<InsightsResponse>(`/insights?period=${period}`),
};

/** Объяснение одного инсайта локальной моделью (поток NDJSON, как у чата).
 * От клиента уходит только id и период — текст для модели собирает backend. */
export function streamInsightExplanation(
  insightId: string,
  period: InsightPeriodKey,
  options: { signal: AbortSignal; onEvent: (event: StreamEvent) => void },
): Promise<void> {
  return postNdjson("/api/v1/insights/explain", { insight_id: insightId, period }, options);
}
