import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/render";

import { DataTransferPage } from "./DataTransferPage";

const api = vi.hoisted(() => ({
  downloadExport: vi.fn(),
  previewBackup: vi.fn(),
  restoreBackup: vi.fn(),
  previewCsv: vi.fn(),
  commitCsv: vi.fn(),
}));

vi.mock("@/lib/api/dataTransfer", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/api/dataTransfer")>();
  return { ...real, dataTransferApi: api };
});
vi.mock("@/lib/api/accounts", () => ({
  accountsApi: {
    list: async () => [
      { id: 1, name: "Сбер", type: "bank", currency: "RUB", initial_balance_minor: 0, is_active: true, balance: { minor: 0, currency: "RUB" } },
    ],
  },
}));
vi.mock("@/lib/api/categories", () => ({
  categoriesApi: {
    list: async () => [
      { id: 11, name: "Продукты", type: "expense", icon: null, parent_id: null, is_default: true, is_archived: false },
    ],
  },
}));

const COUNTS = {
  accounts: 4,
  categories: 33,
  transactions: 184,
  transfers: 12,
  debts: 3,
  debt_payments: 8,
  budgets: 7,
  recurring_transactions: 5,
  recurring_transaction_runs: 9,
  goals: 3,
  goal_entries: 12,
  notifications: 4,
};

const VALID_PREVIEW = {
  valid: true,
  errors: [],
  errors_total: 0,
  version: 1,
  exported_at: "2026-10-08T09:00:00Z",
  base_currency: "RUB",
  counts: COUNTS,
};

function csvPreview(over: Record<string, unknown> = {}) {
  return {
    encoding: "utf-8",
    delimiter: ";",
    headers: ["Дата", "Сумма", "Счёт", "Категория"],
    fields: [
      { key: "occurred_at", label: "Дата", required: true },
      { key: "amount", label: "Сумма", required: true },
      { key: "account", label: "Счёт", required: false },
      { key: "category", label: "Категория", required: true },
    ],
    mapping: { occurred_at: "Дата", amount: "Сумма", amount_minor: null, type: null, account: "Счёт", category: "Категория", comment: null, currency: null },
    suggested_mapping: {},
    mapping_errors: [],
    total_rows: 3,
    new_rows: 3,
    duplicate_rows: 0,
    skipped_rows: 0,
    error_rows: 0,
    errors: [],
    errors_total: 0,
    unknown_accounts: [],
    unknown_categories: [],
    new_accounts: [],
    new_categories: [],
    sample: [
      { row: 2, status: "new", occurred_at: "2026-10-01T09:00:00Z", type: "expense", amount_minor: 120_050, currency: "RUB", account: "Сбер", category: "Продукты", comment: "Хлеб" },
    ],
    can_import: true,
    ...over,
  };
}

const backupFile = () => new File(['{"format":"finance-ai-backup"}'], "finance-ai-backup-2026-10-08.json", { type: "application/json" });
const csvFile = () => new File(["Дата;Сумма\n2026-10-01;-10"], "ops.csv", { type: "text/csv" });

function chooseFile(label: string, file: File) {
  fireEvent.change(screen.getByLabelText(label), { target: { files: [file] } });
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
});

describe("Экспорт", () => {
  it("кнопки скачивания вызывают нужные выгрузки", async () => {
    api.downloadExport.mockResolvedValue("file");
    renderWithProviders(<DataTransferPage />);
    fireEvent.click(screen.getByRole("button", { name: /Скачать backup/ }));
    await waitFor(() => expect(api.downloadExport).toHaveBeenCalledWith("/export/backup"));
    fireEvent.click(screen.getByRole("button", { name: /Скачать CSV/ }));
    await waitFor(() => expect(api.downloadExport).toHaveBeenCalledWith("/export/transactions.csv"));
    fireEvent.click(screen.getByRole("button", { name: /Долги/ }));
    await waitFor(() => expect(api.downloadExport).toHaveBeenCalledWith("/export/debts.csv"));
  });

  it("ошибка скачивания показывается в окне приложения", async () => {
    api.downloadExport.mockRejectedValue(new Error("network"));
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});
    renderWithProviders(<DataTransferPage />);
    fireEvent.click(screen.getByRole("button", { name: /Скачать backup/ }));
    expect(await screen.findByText("Не удалось скачать файл")).toBeTruthy();
    expect(alertSpy).not.toHaveBeenCalled();
  });
});

describe("Восстановление из backup", () => {
  it("показывает preview со сводкой и ничего не восстанавливает до подтверждения", async () => {
    api.previewBackup.mockResolvedValue(VALID_PREVIEW);
    renderWithProviders(<DataTransferPage />);
    const file = backupFile();
    chooseFile("Файл резервной копии", file);

    expect(await screen.findByText("Восстановление из резервной копии")).toBeTruthy();
    expect(api.previewBackup).toHaveBeenCalledWith(file);
    expect(screen.getByTestId("count-transactions").textContent).toBe("184");
    expect(screen.getByTestId("count-goal_entries").textContent).toBe("12");
    expect(screen.getByText("Данные ещё не импортированы.")).toBeTruthy();
    expect(screen.getByText(/заменит текущие данные приложения/)).toBeTruthy();
    expect(api.restoreBackup).not.toHaveBeenCalled();
  });

  it("отмена закрывает окно без восстановления", async () => {
    api.previewBackup.mockResolvedValue(VALID_PREVIEW);
    renderWithProviders(<DataTransferPage />);
    chooseFile("Файл резервной копии", backupFile());
    await screen.findByText("Восстановление из резервной копии");
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(screen.queryByText("Восстановление из резервной копии")).toBeNull();
    expect(api.restoreBackup).not.toHaveBeenCalled();
  });

  it("восстанавливает после явного подтверждения", async () => {
    api.previewBackup.mockResolvedValue(VALID_PREVIEW);
    api.restoreBackup.mockResolvedValue({ restored: true, counts: COUNTS });
    renderWithProviders(<DataTransferPage />);
    const file = backupFile();
    chooseFile("Файл резервной копии", file);
    fireEvent.click(await screen.findByRole("button", { name: "Восстановить" }));
    await waitFor(() => expect(api.restoreBackup).toHaveBeenCalledWith(file));
    expect(await screen.findByText("Данные восстановлены")).toBeTruthy();
  });

  it("невалидный backup: ошибки и никакой кнопки восстановления", async () => {
    api.previewBackup.mockResolvedValue({
      valid: false,
      errors: ["Эта версия резервной копии не поддерживается. (версия 2)"],
      errors_total: 1,
    });
    renderWithProviders(<DataTransferPage />);
    chooseFile("Файл резервной копии", backupFile());
    expect(await screen.findByText("Резервная копия не прошла проверку")).toBeTruthy();
    expect(screen.getByText(/версия резервной копии не поддерживается/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Восстановить" })).toBeNull();
    expect(api.restoreBackup).not.toHaveBeenCalled();
  });

  it("ошибка восстановления показывается в окне", async () => {
    api.previewBackup.mockResolvedValue(VALID_PREVIEW);
    api.restoreBackup.mockRejectedValue(new Error("boom"));
    renderWithProviders(<DataTransferPage />);
    chooseFile("Файл резервной копии", backupFile());
    fireEvent.click(await screen.findByRole("button", { name: "Восстановить" }));
    expect(await screen.findByText("Не удалось восстановить данные")).toBeTruthy();
  });
});

describe("Импорт CSV", () => {
  it("показывает preview и импортирует только после подтверждения", async () => {
    api.previewCsv.mockResolvedValue(csvPreview());
    api.commitCsv.mockResolvedValue({ created: 3, duplicates_skipped: 0, skipped: 0, created_accounts: 0, created_categories: 0 });
    renderWithProviders(<DataTransferPage />);
    chooseFile("CSV-файл с операциями", csvFile());

    const dialog = await screen.findByRole("dialog", { name: "Импорт операций: ops.csv" });
    expect(await within(dialog).findByText("Будут добавлены")).toBeTruthy();
    expect(within(dialog).getByText("Хлеб")).toBeTruthy();
    expect(within(dialog).getByText(/Импорт добавит новые операции в текущие данные/)).toBeTruthy();
    expect(api.previewCsv).toHaveBeenCalledTimes(1);
    const [base64, options] = api.previewCsv.mock.calls[0]!;
    expect(typeof base64).toBe("string");
    expect(options.mapping).toBeNull();
    expect(api.commitCsv).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Импортировать (3)" }));
    await waitFor(() => expect(api.commitCsv).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Импорт завершён")).toBeTruthy();
    expect(screen.getByText(/Добавлено операций: 3/)).toBeTruthy();
  });

  it("отмена не импортирует", async () => {
    api.previewCsv.mockResolvedValue(csvPreview());
    renderWithProviders(<DataTransferPage />);
    chooseFile("CSV-файл с операциями", csvFile());
    const dialog = await screen.findByRole("dialog", { name: "Импорт операций: ops.csv" });
    fireEvent.click(await within(dialog).findByRole("button", { name: "Отмена" }));
    expect(screen.queryByRole("dialog", { name: "Импорт операций: ops.csv" })).toBeNull();
    expect(api.commitCsv).not.toHaveBeenCalled();
  });

  it("ошибки по строкам блокируют импорт", async () => {
    api.previewCsv.mockResolvedValue(
      csvPreview({
        new_rows: 1,
        error_rows: 2,
        can_import: false,
        errors: [
          { row: 17, message: "счёт «Тинкофф» не найден" },
          { row: 24, message: "некорректная сумма «abc»" },
        ],
        errors_total: 2,
      }),
    );
    renderWithProviders(<DataTransferPage />);
    chooseFile("CSV-файл с операциями", csvFile());
    expect(await screen.findByText("Строка 17: счёт «Тинкофф» не найден")).toBeTruthy();
    expect(screen.getByText("Строка 24: некорректная сумма «abc»")).toBeTruthy();
    const button = screen.getByRole("button", { name: "Импортировать (1)" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("изменение сопоставления колонок перепроверяет файл с новым mapping", async () => {
    api.previewCsv.mockResolvedValue(csvPreview());
    renderWithProviders(<DataTransferPage />);
    chooseFile("CSV-файл с операциями", csvFile());
    fireEvent.change(await screen.findByLabelText("Колонка для поля «Счёт»"), { target: { value: "" } });
    await waitFor(() => expect(api.previewCsv).toHaveBeenCalledTimes(2));
    const options = api.previewCsv.mock.calls[1]![1];
    expect(options.mapping.account).toBeNull();
    expect(options.mapping.occurred_at).toBe("Дата");
  });

  it("неизвестный счёт: создание только по явному выбору пользователя", async () => {
    api.previewCsv.mockResolvedValue(
      csvPreview({
        can_import: false,
        error_rows: 3,
        unknown_accounts: [{ key: "тинькофф", name: "Тинькофф", rows: 3, currencies: ["RUB"] }],
      }),
    );
    renderWithProviders(<DataTransferPage />);
    chooseFile("CSV-файл с операциями", csvFile());
    const select = await screen.findByLabelText("Счёт «Тинькофф»");
    fireEvent.change(select, { target: { value: "create" } });
    await waitFor(() => expect(api.previewCsv).toHaveBeenCalledTimes(2));
    expect(api.previewCsv.mock.calls[1]![1].account_resolutions).toEqual({ тинькофф: { action: "create" } });
    fireEvent.change(select, { target: { value: "map:1" } });
    await waitFor(() => expect(api.previewCsv).toHaveBeenCalledTimes(3));
    expect(api.previewCsv.mock.calls[2]![1].account_resolutions).toEqual({ тинькофф: { action: "map", target_id: 1 } });
    expect(api.commitCsv).not.toHaveBeenCalled();
  });

  it("ошибка импорта показывается, данные не помечаются как импортированные", async () => {
    api.previewCsv.mockResolvedValue(csvPreview());
    api.commitCsv.mockRejectedValue(new Error("boom"));
    renderWithProviders(<DataTransferPage />);
    chooseFile("CSV-файл с операциями", csvFile());
    fireEvent.click(await screen.findByRole("button", { name: "Импортировать (3)" }));
    expect(await screen.findByText("Импорт не выполнен")).toBeTruthy();
    expect(screen.queryByText("Импорт завершён")).toBeNull();
  });

  it("нечитаемый файл: понятная ошибка", async () => {
    api.previewCsv.mockRejectedValue(new Error("x"));
    renderWithProviders(<DataTransferPage />);
    chooseFile("CSV-файл с операциями", csvFile());
    expect(await screen.findByText("Не удалось прочитать CSV")).toBeTruthy();
    expect(api.commitCsv).not.toHaveBeenCalled();
  });
});
