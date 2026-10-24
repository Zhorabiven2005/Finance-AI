import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Analytics } from "@/lib/api/analytics";
import type { Transaction } from "@/lib/api/transactions";
import { apiError, renderWithProviders, rub } from "@/test/render";

import { AnalyticsPage } from "./AnalyticsPage";

const analytics = vi.hoisted(() => ({ get: vi.fn() }));
const tx = vi.hoisted(() => ({ get: vi.fn(), update: vi.fn(), create: vi.fn() }));
vi.mock("@/lib/api/analytics", () => ({ analyticsApi: analytics }));
vi.mock("@/lib/api/transactions", () => ({ transactionsApi: tx }));
vi.mock("@/lib/api/accounts", () => ({
  accountsApi: {
    list: async () => [
      { id: 1, name: "Сбер", type: "bank", currency: "RUB", initial_balance_minor: 0, is_active: true, balance: rub(0) },
    ],
  },
}));
vi.mock("@/lib/api/categories", () => ({
  categoriesApi: {
    list: async () => [
      { id: 10, name: "Продукты", type: "expense", icon: null, parent_id: null, is_default: true, is_archived: false },
    ],
  },
}));

const DATA: Analytics = {
  date_from: "2026-10-01",
  date_to: "2026-10-31",
  currency: "RUB",
  granularity: "day",
  summary: { income: rub(0), expense: rub(4_150_000), balance: rub(-4_150_000), transaction_count: 2 },
  comparison: { income_change_percent: null, expense_change_percent: null },
  timeseries: [],
  category_breakdown: [],
  top_expenses: [
    { transaction_id: 77, amount: rub(4_000_000), category_name: "Долги", account_name: "Сбер", occurred_at: "2026-10-02T10:00:00Z", comment: "Первый платёж" },
    { transaction_id: 5, amount: rub(150_000), category_name: "Продукты", account_name: "Сбер", occurred_at: "2026-10-05T10:00:00Z", comment: null },
  ],
} as unknown as Analytics;

function op(over: Partial<Transaction>): Transaction {
  return {
    id: 5,
    account_id: 1,
    category_id: 10,
    type: "expense",
    amount: rub(150_000),
    occurred_at: "2026-10-05T10:00:00Z",
    comment: null,
    debt_id: null,
    debt_name: null,
    ...over,
  };
}

beforeEach(() => {
  analytics.get.mockReset();
  for (const fn of Object.values(tx)) fn.mockReset();
  analytics.get.mockResolvedValue(DATA);
});

async function openTopExpense(name: RegExp) {
  const list = (await screen.findByRole("heading", { name: "Крупнейшие расходы" })).closest("section")!;
  fireEvent.click(within(list).getByRole("button", { name }));
}

describe("Крупнейшие расходы", () => {
  it("платёж по долгу не открывается как обычная операция — только ссылки на долг и журнал", async () => {
    tx.get.mockResolvedValue(op({ id: 77, category_id: 11, amount: rub(4_000_000), debt_id: 3, debt_name: "Банк" }));
    renderWithProviders(<AnalyticsPage />);
    await openTopExpense(/Первый платёж/);
    const dialog = await screen.findByRole("dialog", { name: "Платёж по долгу" });
    expect(within(dialog).getByText(/платёж по долгу «Банк»/)).toBeTruthy();
    expect(within(dialog).getByRole("link", { name: "Открыть долг" }).getAttribute("href")).toBe("/debts/3");
    expect(within(dialog).getByRole("link", { name: "Показать в журнале" }).getAttribute("href")).toBe("/transactions?tx=77");
    expect(within(dialog).queryByRole("button", { name: "Сохранить" })).toBeNull();
    expect(screen.queryByRole("dialog", { name: /Изменить расход/ })).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Понятно" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(tx.update).not.toHaveBeenCalled();
  });

  it("обычная операция открывается в форме; после сохранения аналитика перезапрашивается", async () => {
    tx.get.mockResolvedValue(op({}));
    tx.update.mockResolvedValue(op({ amount: rub(200_000) }));
    renderWithProviders(<AnalyticsPage />);
    await openTopExpense(/Продукты/);
    const dialog = await screen.findByRole("dialog", { name: "Изменить расход" });
    await within(dialog).findByRole("option", { name: "Сбер" });
    fireEvent.change(within(dialog).getByPlaceholderText("0"), { target: { value: "2000" } });
    const callsBefore = analytics.get.mock.calls.length;
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(tx.update).toHaveBeenCalledWith(5, expect.objectContaining({ amount_minor: 200_000 }));
    await waitFor(() => expect(analytics.get.mock.calls.length).toBeGreaterThan(callsBefore));
  });

  it("если операцию не удалось загрузить — сообщение в окне приложения", async () => {
    tx.get.mockRejectedValue(apiError(404, "Операция не найдена"));
    renderWithProviders(<AnalyticsPage />);
    await openTopExpense(/Продукты/);
    const dialog = await screen.findByRole("dialog", { name: "Не удалось открыть операцию" });
    expect(within(dialog).getByText("Операция не найдена")).toBeTruthy();
  });
});
