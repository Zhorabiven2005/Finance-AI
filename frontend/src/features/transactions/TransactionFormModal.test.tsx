import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiError, deferred, renderWithProviders, rub } from "@/test/render";

import { TransactionFormModal } from "./TransactionFormModal";
import { TransferFormModal } from "./TransferFormModal";

const tx = vi.hoisted(() => ({ create: vi.fn(), update: vi.fn() }));
const tr = vi.hoisted(() => ({ create: vi.fn() }));
vi.mock("@/lib/api/transactions", () => ({ transactionsApi: tx }));
vi.mock("@/lib/api/transfers", () => ({ transfersApi: tr }));
vi.mock("@/lib/api/accounts", () => ({
  accountsApi: {
    list: async () => [
      { id: 1, name: "Сбер", type: "bank", currency: "RUB", initial_balance_minor: 0, is_active: true, balance: rub(0) },
      { id: 2, name: "Наличные", type: "cash", currency: "RUB", initial_balance_minor: 0, is_active: true, balance: rub(0) },
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

beforeEach(() => {
  for (const fn of [...Object.values(tx), ...Object.values(tr)]) fn.mockReset();
});

async function fillExpense(amount: string) {
  await screen.findByRole("option", { name: "Сбер" });
  await screen.findByRole("option", { name: "Продукты" });
  const [account, category] = screen.getAllByRole("combobox");
  fireEvent.change(account!, { target: { value: "1" } });
  fireEvent.change(category!, { target: { value: "10" } });
  fireEvent.change(screen.getByPlaceholderText("0"), { target: { value: amount } });
}

describe("Ошибки проверки форм видны пользователю", () => {
  it("некорректная сумма — конкретное сообщение, запрос не отправляется, форма открыта", async () => {
    const onSaved = vi.fn();
    renderWithProviders(<TransactionFormModal type="expense" transaction={null} onClose={() => {}} onSaved={onSaved} />);
    await fillExpense("абв");
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText("Некорректная сумма")).toBeTruthy();
    expect(screen.queryByText("Не удалось сохранить операцию")).toBeNull();
    expect(tx.create).not.toHaveBeenCalled();
    expect(onSaved).not.toHaveBeenCalled();
    expect(screen.getByPlaceholderText("0")).toHaveProperty("value", "абв");
  });

  it("перевод на тот же счёт — понятное сообщение", async () => {
    renderWithProviders(<TransferFormModal onClose={() => {}} onSaved={() => {}} />);
    await screen.findAllByRole("option", { name: "Сбер" });
    const [from, to] = screen.getAllByRole("combobox");
    fireEvent.change(from!, { target: { value: "1" } });
    fireEvent.change(to!, { target: { value: "1" } });
    fireEvent.change(screen.getByPlaceholderText("0"), { target: { value: "100" } });
    fireEvent.click(screen.getByRole("button", { name: /Перевести|Сохранить/ }));
    expect(await screen.findByText("Счёт-источник и счёт-получатель должны различаться")).toBeTruthy();
    expect(tr.create).not.toHaveBeenCalled();
  });

  it("ошибка backend остаётся в форме, введённые данные сохраняются", async () => {
    tx.create.mockRejectedValue(apiError(404, "Счёт не найден"));
    renderWithProviders(<TransactionFormModal type="expense" transaction={null} onClose={() => {}} onSaved={() => {}} />);
    await fillExpense("1500");
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText("Счёт не найден")).toBeTruthy();
    expect(screen.getByPlaceholderText("0")).toHaveProperty("value", "1500");
  });

  it("повторное нажатие «Сохранить» во время запроса не создаёт вторую операцию", async () => {
    const pending = deferred();
    tx.create.mockReturnValue(pending.promise);
    const onSaved = vi.fn();
    renderWithProviders(<TransactionFormModal type="expense" transaction={null} onClose={() => {}} onSaved={onSaved} />);
    await fillExpense("1500");
    const save = screen.getByRole("button", { name: "Сохранить" }) as HTMLButtonElement;
    fireEvent.click(save);
    await waitFor(() => expect(save.disabled).toBe(true));
    fireEvent.click(save);
    expect(tx.create).toHaveBeenCalledTimes(1);
    expect(tx.create.mock.calls[0]![0]).toMatchObject({ amount_minor: 150_000, account_id: 1, category_id: 10 });
    pending.resolve();
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
  });
});
