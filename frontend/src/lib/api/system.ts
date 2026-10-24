import { api } from "@/lib/api/client";
import type { Currency } from "@/lib/money";

export interface HealthResponse {
  status: string;
  app: string;
  version: string;
  database: string;
  ai_configured: boolean;
}

export interface AppSettingsResponse {
  base_currency: string;
  locale: string;
  currency: Currency;
}

export const systemApi = {
  health: () => api.get<HealthResponse>("/health"),
  settings: () => api.get<AppSettingsResponse>("/settings"),
  currencies: () => api.get<Currency[]>("/currencies"),
};
