import { ApiError, api, apiRequest } from "@/lib/api/client";

export type BackupSection =
  | "accounts"
  | "categories"
  | "transactions"
  | "transfers"
  | "debts"
  | "debt_payments"
  | "budgets"
  | "recurring_transactions"
  | "recurring_transaction_runs"
  | "goals"
  | "goal_entries"
  | "notifications";

export type BackupPreview =
  | { valid: false; errors: string[]; errors_total: number }
  | {
      valid: true;
      errors: [];
      errors_total: 0;
      version: number;
      exported_at: string;
      base_currency: string;
      counts: Record<BackupSection, number>;
    };

export type CsvField =
  | "occurred_at"
  | "amount"
  | "amount_minor"
  | "type"
  | "account"
  | "category"
  | "comment"
  | "currency";

export type Resolution = { action: "map"; target_id: number } | { action: "create" };

export interface CsvImportOptions {
  mapping?: Partial<Record<CsvField, string | null>> | null;
  default_account_id?: number | null;
  tz_offset_minutes?: number;
  account_resolutions?: Record<string, Resolution>;
  category_resolutions?: Record<string, Resolution>;
}

export interface CsvRowSample {
  row: number;
  status: "new" | "duplicate" | "skipped" | "error";
  occurred_at: string | null;
  type: "income" | "expense" | null;
  amount_minor: number | null;
  currency: string | null;
  account: string | null;
  category: string | null;
  comment: string | null;
}

export interface CsvPreview {
  encoding: string;
  delimiter: string;
  headers: string[];
  fields: { key: CsvField; label: string; required: boolean }[];
  mapping: Record<CsvField, string | null>;
  suggested_mapping: Record<CsvField, string | null>;
  mapping_errors: string[];
  total_rows: number;
  new_rows: number;
  duplicate_rows: number;
  skipped_rows: number;
  error_rows: number;
  errors: { row: number; message: string }[];
  errors_total: number;
  unknown_accounts: { key: string; name: string; rows: number; currencies: string[] }[];
  unknown_categories: { key: string; name: string; type: "income" | "expense"; rows: number }[];
  new_accounts: { name: string; currency: string }[];
  new_categories: { name: string; type: string }[];
  sample: CsvRowSample[];
  can_import: boolean;
}

export interface CsvCommitResult {
  created: number;
  duplicates_skipped: number;
  skipped: number;
  created_accounts: number;
  created_categories: number;
}

export const EXPORTS = {
  backup: "/export/backup",
  transactions: "/export/transactions.csv",
  transfers: "/export/transfers.csv",
  accounts: "/export/accounts.csv",
  debts: "/export/debts.csv",
  goals: "/export/goals.csv",
} as const;

function filenameFrom(disposition: string | null, fallback: string): string {
  const match = disposition?.match(/filename="([^"]+)"/);
  return match?.[1] ?? fallback;
}

/** Отдаёт браузеру файл на сохранение (без перехода со страницы). */
export function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function downloadExport(path: string): Promise<string> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`);
  } catch {
    throw new ApiError("Backend недоступен. Проверьте, что сервер запущен.", 0);
  }
  if (!response.ok) throw new ApiError(`Не удалось скачать файл (код ${response.status})`, response.status);
  const filename = filenameFrom(response.headers.get("Content-Disposition"), path.split("/").pop() ?? "export");
  triggerDownload(await response.blob(), filename);
  return filename;
}

export function fileToBase64(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result ?? "");
      resolve(result.slice(result.indexOf(",") + 1));
    };
    reader.onerror = () => reject(new Error("Не удалось прочитать файл"));
    reader.readAsDataURL(file);
  });
}

export const dataTransferApi = {
  downloadExport,
  previewBackup: (file: Blob) =>
    apiRequest<BackupPreview>("/import/backup/preview", { method: "POST", body: file }),
  restoreBackup: (file: Blob) =>
    apiRequest<{ restored: true; counts: Record<BackupSection, number> }>(
      "/import/backup/restore?confirm=true",
      { method: "POST", body: file },
    ),
  previewCsv: (fileBase64: string, options: CsvImportOptions) =>
    api.post<CsvPreview>("/import/transactions/preview", { file_base64: fileBase64, options }),
  commitCsv: (fileBase64: string, options: CsvImportOptions) =>
    api.post<CsvCommitResult>("/import/transactions/commit", {
      file_base64: fileBase64,
      options,
      confirm: true,
    }),
};
