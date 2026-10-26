import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders, rub } from "@/test/render";

import { DashboardPage } from "./DashboardPage";

const state = vi.hoisted(() => ({
  debts: [] as unknown[],
  budgets: [] as unknown[],
  goals: [] as unknown[],
  recent: [] as unknown[],
}));

vi.mock("@/lib/api/dashboard", () => ({
  dashboardApi: {
    get: async () => ({
      net_worth: { minor: 5_000_000, currency: "RUB" },
      accounts: [
        {
          id: 1,
          name: "Сбер",
          type: "bank",
          currency: "RUB",
          initial_balance_minor: 0,
          is_active: true,
          balance: { minor: 5_000_000, currency: "RUB" },
        },
      ],
      debts: {
        i_owe_total: { minor: 0, currency: "RUB" },
        owed_to_me_total: { minor: 0, currency: "RUB" },
        items: state.debts,
        totals_by_currency: state.debts.length
          ? [{ currency: "RUB", i_owe: { minor: 3_000_000, currency: "RUB" }, owed_to_me: { minor: 0, currency: "RUB" } }]
          : [],
        overdue_count: 0,
      },
      recent_transactions: state.recent,
      top_expenses: [],
    }),
  },
}));
vi.mock("@/lib/api/insights", () => ({
  insightsApi: {
    get: async () => ({
      generated_at: "2026-10-25T00:00:00Z",
      today: "2026-10-25",
      period: { key: "current_month", date_from: "2026-10-01", date_to: "2026-10-31", label: "октябрь 2026", complete: false },
      currencies: [],
      insights: [],
      unavailable: [],
    }),
  },
  streamInsightExplanation: async () => undefined,
}));
vi.mock("@/lib/api/assistant", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/assistant")>()),
  assistantApi: { status: async () => ({ ready: false }) },
}));
vi.mock("@/lib/api/budgets", () => ({ budgetsApi: { list: async () => state.budgets } }));
vi.mock("@/lib/api/goals", () => ({ goalsApi: { list: async () => state.goals } }));
vi.mock("@/lib/api/analytics", () => ({
  analyticsApi: {
    get: async () => ({
      currency: "RUB",
      granularity: "day",
      summary: { income: rub(0), expense: rub(0), balance: rub(0), transaction_count: 0 },
      timeseries: [],
    }),
  },
}));

const debt = {
  id: 1,
  counterparty_name: "Банк",
  direction: "i_owe",
  principal: rub(3_000_000),
  paid: rub(0),
  remaining: rub(3_000_000),
  status: "active",
  due_date: null,
  comment: null,
  paid_percent: 0,
  due_state: "none",
  days_until_due: null,
  created_at: "2026-10-01T00:00:00Z",
};
const budget = {
  id: 1,
  category_id: 1,
  category_name: "Продукты",
  category_icon: null,
  amount: rub(1_000_000),
  year: 2026,
  month: 10,
  spent: rub(100_000),
  remaining: rub(900_000),
  usage_percent: 10,
  status: "ok",
};
const goal = {
  id: 1,
  name: "MacBook",
  description: null,
  target: rub(18_000_000),
  saved: rub(7_200_000),
  remaining: rub(10_800_000),
  progress_percent: 40,
  currency: "RUB",
  target_date: null,
  status: "active",
  created_at: "2026-10-01T00:00:00Z",
};

async function rows(config: { debts?: boolean; budgets?: boolean; goals?: boolean }) {
  state.debts = config.debts ? [debt] : [];
  state.budgets = config.budgets ? [budget] : [];
  state.goals = config.goals ? [goal] : [];
  renderWithProviders(<DashboardPage />);
  await screen.findByText("Дашборд");
  await waitFor(() => expect(screen.getAllByTestId("dashboard-row").length).toBeGreaterThan(0));
  // Бюджеты и цели подгружаются отдельными запросами — ждём их блоки.
  if (config.budgets) await screen.findByText("Бюджеты этого месяца");
  if (config.goals) await screen.findByText("Финансовые цели");
  return screen.getAllByTestId("dashboard-row").map((r) => Number(r.getAttribute("data-blocks")));
}

describe("Dashboard adaptive layout", () => {
  it("no debts/budgets/goals: accounts take the whole row, no empty rows", async () => {
    // [счета] [мини-аналитика + последние операции]
    expect(await rows({})).toEqual([1, 2]);
    expect(screen.queryByText("Долги")).toBeNull();
    expect(screen.queryByText("Бюджеты этого месяца")).toBeNull();
    expect(screen.queryByText("Финансовые цели")).toBeNull();
  });

  it("budgets only: budgets row is a single full-width block", async () => {
    expect(await rows({ budgets: true })).toEqual([1, 1, 2]);
  });

  it("goals only: goals row is a single full-width block", async () => {
    expect(await rows({ goals: true })).toEqual([1, 1, 2]);
  });

  it("budgets + goals: two columns", async () => {
    expect(await rows({ budgets: true, goals: true })).toEqual([1, 2, 2]);
  });

  it("debts + budgets", async () => {
    expect(await rows({ debts: true, budgets: true })).toEqual([2, 1, 2]);
  });

  it("debts + goals", async () => {
    expect(await rows({ debts: true, goals: true })).toEqual([2, 1, 2]);
  });

  it("debts only", async () => {
    expect(await rows({ debts: true })).toEqual([2, 2]);
  });

  it("all sections", async () => {
    expect(await rows({ debts: true, budgets: true, goals: true })).toEqual([2, 2, 2]);
  });

  it("debts block stays above accounts when debts exist", async () => {
    await rows({ debts: true });
    const html = document.body.innerHTML;
    expect(html.indexOf("Долги")).toBeGreaterThan(-1);
    expect(html.indexOf("Долги")).toBeLessThan(html.indexOf("Счета"));
  });

  it("debt payment appears as a normal recent operation with the debt name", async () => {
    state.recent = [
      {
        id: 7,
        account_id: 1,
        category_id: 32,
        type: "expense",
        amount: rub(1_000_000),
        occurred_at: "2026-10-05T10:00:00Z",
        comment: null,
        debt_id: 1,
        debt_name: "Банк",
        account_name: "Сбер",
        category_name: "Погашение долга",
        category_icon: null,
      },
    ];
    await rows({});
    expect(screen.getByText("Погашение долга")).toBeTruthy();
    expect(screen.getByText(/Долг: Банк/)).toBeTruthy();
    state.recent = [];
  });
});
