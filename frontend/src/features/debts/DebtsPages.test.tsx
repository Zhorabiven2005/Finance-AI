import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Debt } from "@/lib/api/debts";
import { debtDueLabel, sortDebts } from "@/lib/debtDue";
import { apiError, renderWithProviders, rub } from "@/test/render";

import { DebtDetailPage } from "./DebtDetailPage";
import { DebtsPage } from "./DebtsPage";

const api = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  payments: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
  removePayment: vi.fn(),
  addPayment: vi.fn(),
  updatePayment: vi.fn(),
  create: vi.fn(),
}));
vi.mock("@/lib/api/debts", () => ({ debtsApi: api }));
vi.mock("@/lib/api/accounts", () => ({
  accountsApi: { list: async () => [{ id: 1, name: "Сбер", type: "bank", currency: "RUB", initial_balance_minor: 0, is_active: true, balance: rub(0) }] },
}));

function debt(over: Partial<Debt>): Debt {
  return {
    id: 1,
    counterparty_name: "Банк",
    direction: "i_owe",
    principal: rub(10_000_000),
    paid: rub(4_000_000),
    remaining: rub(6_000_000),
    status: "partially_paid",
    due_date: null,
    comment: null,
    paid_percent: 40,
    due_state: "none",
    days_until_due: null,
    created_at: "2026-09-01T10:00:00Z",
    ...over,
  };
}

describe("Подписи сроков долга", () => {
  it.each([
    [{ due_state: "none", days_until_due: null }, "Срок не задан", "neutral"],
    [{ due_state: "upcoming", days_until_due: 30 }, "Через 30 дней", "neutral"],
    [{ due_state: "soon", days_until_due: 3 }, "Скоро: через 3 дня", "warn"],
    [{ due_state: "today", days_until_due: 0 }, "Срок сегодня", "warn"],
    [{ due_state: "overdue", days_until_due: -1 }, "Просрочен на 1 день", "danger"],
    [{ due_state: "paid", days_until_due: -5 }, "Погашен", "ok"],
  ] as const)("%o", (d, label, tone) => {
    expect(debtDueLabel(d)).toEqual({ label, tone });
  });

  it("сортировка: просроченные первыми; остаток сравнивается внутри валюты", () => {
    const list = [
      debt({ id: 1, due_state: "none" }),
      debt({ id: 2, due_state: "soon", due_date: "2026-10-20" }),
      debt({ id: 3, due_state: "overdue", due_date: "2026-10-01" }),
      debt({ id: 4, remaining: { minor: 100, currency: "USD" }, due_state: "today", due_date: "2026-10-15" }),
    ];
    expect(sortDebts(list, "urgency").map((d) => d.id)).toEqual([3, 4, 2, 1]);
    expect(sortDebts(list, "due").map((d) => d.id)).toEqual([3, 4, 2, 1]);
    expect(sortDebts(list, "remaining").map((d) => d.remaining.currency)).toEqual(["RUB", "RUB", "RUB", "USD"]);
  });
});

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
});

describe("Список долгов", () => {
  it("ошибка загрузки — не «долгов нет», а повтор", async () => {
    api.list.mockRejectedValueOnce(apiError(0, "offline")).mockResolvedValueOnce([debt({})]);
    renderWithProviders(<DebtsPage />);
    const error = await screen.findByRole("alert");
    expect(screen.queryByText("Активных долгов нет.")).toBeNull();
    fireEvent.click(within(error).getByRole("button", { name: "Повторить" }));
    expect(await screen.findAllByTestId("debt-row")).toHaveLength(1);
  });

  it("показывает сроки, прогресс, вкладки и сортировку", async () => {
    api.list.mockResolvedValue([
      debt({ id: 1, counterparty_name: "Без срока" }),
      debt({ id: 2, counterparty_name: "Просрочен", due_state: "overdue", days_until_due: -3, due_date: "2026-10-12" }),
      debt({ id: 3, counterparty_name: "Закрыт", status: "paid", due_state: "paid", paid_percent: 100, remaining: rub(0) }),
    ]);
    renderWithProviders(<DebtsPage />);
    const rows = await screen.findAllByTestId("debt-row");
    expect(rows.map((r) => within(r).getByRole("link").textContent)).toEqual(["Просрочен", "Без срока"]);
    expect(within(rows[0]!).getByText("Просрочен на 3 дня")).toBeTruthy();
    expect(within(rows[1]!).getByText("Срок не задан")).toBeTruthy();
    expect(within(rows[0]!).getByRole("progressbar").getAttribute("aria-valuenow")).toBe("40");
    expect(screen.getByText("Просрочено долгов: 1")).toBeTruthy();
    expect(within(rows[0]!).getByRole("link").getAttribute("href")).toBe("/debts/2");

    fireEvent.click(screen.getByRole("tab", { name: "Погашенные (1)" }));
    const paid = await screen.findAllByTestId("debt-row");
    expect(paid).toHaveLength(1);
    expect(within(paid[0]!).getByText("Погашен")).toBeTruthy();
  });

  it("удаление долга — через окно приложения", async () => {
    api.list.mockResolvedValue([debt({})]);
    api.remove.mockResolvedValue(undefined);
    const confirmSpy = vi.spyOn(window, "confirm");
    renderWithProviders(<DebtsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Удалить" }));
    expect(screen.getByText("Удалить долг «Банк»?")).toBeTruthy();
    expect(api.remove).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Удалить" }));
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith(1));
    expect(confirmSpy).not.toHaveBeenCalled();
  });
});

function renderDetail() {
  return renderWithProviders(
    <Routes>
      <Route path="/debts/:debtId" element={<DebtDetailPage />} />
    </Routes>,
    { route: "/debts/1" },
  );
}

describe("Карточка долга", () => {
  it("показывает суммы, прогресс, срок и историю платежей со связанной операцией", async () => {
    api.get.mockResolvedValue(debt({ due_date: "2026-10-20", due_state: "soon", days_until_due: 5, comment: "Ипотека" }));
    api.payments.mockResolvedValue([
      { id: 10, debt_id: 1, account_id: 1, transaction_id: 77, amount: rub(3_000_000), paid_at: "2026-10-01T10:00:00Z", comment: "аванс" },
      { id: 11, debt_id: 1, account_id: null, transaction_id: null, amount: rub(1_000_000), paid_at: "2026-10-05T10:00:00Z", comment: null },
    ]);
    renderDetail();
    expect(await screen.findByRole("heading", { name: "Банк" })).toBeTruthy();
    expect(screen.getByText("Первоначальная сумма").nextElementSibling?.textContent).toContain("100");
    expect(screen.getByText("Прогресс").nextElementSibling?.textContent).toBe("40%");
    expect(screen.getByText("Скоро: через 5 дней")).toBeTruthy();
    expect(screen.getByText("Ипотека")).toBeTruthy();
    const rows = await screen.findAllByTestId("payment-row");
    // Ссылка ведёт на конкретную операцию по её id, а не в общий журнал.
    expect(within(rows[0]!).getByRole("link", { name: "№77 в журнале" }).getAttribute("href")).toBe("/transactions?tx=77");
    expect(within(rows[0]!).getByText("Сбер")).toBeTruthy();
    expect(within(rows[1]!).getByText("не влияет на счёт")).toBeTruthy();
  });

  it("удаление платежа — после подтверждения", async () => {
    api.get.mockResolvedValue(debt({}));
    api.payments.mockResolvedValue([
      { id: 10, debt_id: 1, account_id: 1, transaction_id: 77, amount: rub(3_000_000), paid_at: "2026-10-01T10:00:00Z", comment: null },
    ]);
    api.removePayment.mockResolvedValue(undefined);
    renderDetail();
    fireEvent.click(await screen.findByRole("button", { name: "Удалить платёж" }));
    expect(api.removePayment).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Удалить" }));
    await waitFor(() => expect(api.removePayment).toHaveBeenCalledWith(1, 10));
  });

  it("ошибка удаления платежа видна в окне, повтор возможен, отмена ничего не удаляет", async () => {
    api.get.mockResolvedValue(debt({}));
    api.payments.mockResolvedValue([
      { id: 10, debt_id: 1, account_id: 1, transaction_id: 77, amount: rub(3_000_000), paid_at: "2026-10-01T10:00:00Z", comment: null },
    ]);
    api.removePayment.mockRejectedValueOnce(apiError(404, "Платёж не найден")).mockResolvedValueOnce(undefined);
    renderDetail();
    fireEvent.click(await screen.findByRole("button", { name: "Удалить платёж" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Отмена" }));
    expect(api.removePayment).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Удалить платёж" }));
    const dialog = screen.getByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Удалить" }) as HTMLButtonElement;
    fireEvent.click(confirm);
    expect((await within(dialog).findByRole("alert")).textContent).toBe("Платёж не найден");
    await waitFor(() => expect(confirm.disabled).toBe(false));
    fireEvent.click(confirm);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(api.removePayment).toHaveBeenCalledTimes(2);
  });

  it("ошибка загрузки истории платежей — с повтором", async () => {
    api.get.mockResolvedValue(debt({}));
    api.payments.mockRejectedValueOnce(apiError(0, "offline")).mockResolvedValueOnce([]);
    renderDetail();
    const error = await screen.findByRole("alert");
    fireEvent.click(within(error).getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText("Платежей пока нет.")).toBeTruthy();
  });

  it("несуществующий долг", async () => {
    api.get.mockRejectedValue(new Error("404"));
    renderDetail();
    expect(await screen.findByText(/Долг не найден/)).toBeTruthy();
  });
});
