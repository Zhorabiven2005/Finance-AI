import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Transaction } from "@/lib/api/transactions";
import { apiError, deferred, renderWithProviders, rub } from "@/test/render";

import { TransactionsPage } from "./TransactionsPage";

const tx = vi.hoisted(() => ({ list: vi.fn(), get: vi.fn(), remove: vi.fn(), update: vi.fn(), create: vi.fn() }));
const tr = vi.hoisted(() => ({ list: vi.fn(), remove: vi.fn(), create: vi.fn() }));
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
      { id: 11, name: "Долги", type: "expense", icon: null, parent_id: null, is_default: true, is_archived: false },
    ],
  },
}));

function op(over: Partial<Transaction>): Transaction {
  return {
    id: 1,
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

const PAYMENT = op({ id: 77, category_id: 11, amount: rub(4_000_000), comment: "Первый платёж", debt_id: 3, debt_name: "Банк" });
const PAGE = [op({ id: 1 }), op({ id: 2, amount: rub(50_000) })];

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname + location.search}</output>;
}

function renderJournal(route = "/transactions") {
  return renderWithProviders(
    <Routes>
      <Route
        path="/transactions"
        element={
          <>
            <TransactionsPage />
            <LocationProbe />
          </>
        }
      />
    </Routes>,
    { route },
  );
}

const location = () => screen.getByTestId("location").textContent;

let nativeAlert: ReturnType<typeof vi.spyOn>;
let nativeConfirm: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  for (const fn of [...Object.values(tx), ...Object.values(tr)]) fn.mockReset();
  tx.list.mockResolvedValue({ data: PAGE, total: 25 });
  tr.list.mockResolvedValue([]);
  nativeAlert = vi.spyOn(window, "alert").mockImplementation(() => {});
  nativeConfirm = vi.spyOn(window, "confirm").mockImplementation(() => true);
});

afterEach(() => {
  expect(nativeAlert).not.toHaveBeenCalled();
  expect(nativeConfirm).not.toHaveBeenCalled();
  vi.restoreAllMocks();
});

describe("Удаление в журнале", () => {
  it("операция: отмена ничего не удаляет, подтверждение — один запрос и обновление списка", async () => {
    tx.remove.mockResolvedValue(undefined);
    renderJournal();
    const rows = await screen.findAllByTestId("transaction-row");
    fireEvent.click(within(rows[0]!).getByRole("button", { name: "Удалить" }));
    const dialog = screen.getByRole("dialog", { name: "Удалить операцию?" });
    expect(within(dialog).getByText(/баланс счёта «Сбер» пересчитается/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Отмена" }));
    expect(tx.remove).not.toHaveBeenCalled();

    fireEvent.click(within(rows[0]!).getByRole("button", { name: "Удалить" }));
    tx.list.mockResolvedValue({ data: [PAGE[1]!], total: 24 });
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Удалить" }));
    await waitFor(() => expect(screen.getAllByTestId("transaction-row")).toHaveLength(1));
    expect(tx.remove).toHaveBeenCalledTimes(1);
    expect(tx.remove).toHaveBeenCalledWith(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("перевод: подтверждение в окне, ошибка остаётся в окне", async () => {
    tr.list.mockResolvedValue([
      { id: 9, from_account_id: 1, to_account_id: 2, amount: rub(10_000), occurred_at: "2026-10-05T10:00:00Z", comment: null },
    ]);
    const pending = deferred();
    tr.remove.mockReturnValue(pending.promise);
    renderJournal();
    const transfers = await screen.findByRole("heading", { name: "Переводы" });
    fireEvent.click(within(transfers.closest("section")!).getByRole("button", { name: "Удалить" }));
    const dialog = screen.getByRole("dialog", { name: "Удалить перевод?" });
    expect(within(dialog).getByText(/«Сбер» → «Наличные»/)).toBeTruthy();
    const confirm = within(dialog).getByRole("button", { name: "Удалить" }) as HTMLButtonElement;
    fireEvent.click(confirm);
    await waitFor(() => expect(confirm.disabled).toBe(true));
    fireEvent.click(confirm);
    expect(tr.remove).toHaveBeenCalledTimes(1);
    pending.reject(apiError(404, "Перевод не найден"));
    expect((await within(dialog).findByRole("alert")).textContent).toBe("Перевод не найден");
  });

  it("платёж по долгу в журнале нельзя изменить или удалить — только ссылка на его долг", async () => {
    tx.list.mockResolvedValue({ data: [PAYMENT], total: 1 });
    renderJournal();
    const [row] = await screen.findAllByTestId("transaction-row");
    expect(within(row!).queryByRole("button", { name: "Удалить" })).toBeNull();
    expect(within(row!).queryByRole("button", { name: "Изменить" })).toBeNull();
    expect(within(row!).getByRole("link").getAttribute("href")).toBe("/debts/3");
  });

  it("ошибка загрузки журнала — отдельное состояние с повтором", async () => {
    tx.list.mockRejectedValueOnce(apiError(0, "offline")).mockResolvedValue({ data: PAGE, total: 2 });
    renderJournal();
    const error = await screen.findByRole("alert");
    expect(screen.queryByText("Операций пока нет.")).toBeNull();
    fireEvent.click(within(error).getByRole("button", { name: "Повторить" }));
    expect(await screen.findAllByTestId("transaction-row")).toHaveLength(2);
  });
});

describe("Открытие конкретной операции по ссылке ?tx=ID", () => {
  it("открывает именно операцию с этим id, даже если её нет на текущей странице журнала", async () => {
    tx.get.mockResolvedValue(op({ id: 55, amount: rub(123_456), comment: "кофемашина" }));
    renderJournal("/transactions?tx=55");
    const card = await screen.findByRole("region", { name: "Операция №55" });
    await within(card).findByTestId("selected-transaction");
    expect(tx.get).toHaveBeenCalledWith(55);
    expect(within(card).getByText(/кофемашина/)).toBeTruthy();
    expect(within(card).getByText(/1\s?234,56/)).toBeTruthy();
    expect(within(card).getByRole("button", { name: "Изменить" })).toBeTruthy();
    // В текущей странице журнала её нет — подсветки строки тоже нет.
    expect((await screen.findAllByTestId("transaction-row")).some((r) => r.getAttribute("aria-current"))).toBe(false);
  });

  it("если операция есть на странице — её строка подсвечена", async () => {
    tx.get.mockResolvedValue(PAGE[1]!);
    renderJournal("/transactions?tx=2");
    await screen.findByRole("region", { name: "Операция №2" });
    const rows = await screen.findAllByTestId("transaction-row");
    expect(rows.map((r) => r.getAttribute("aria-current"))).toEqual([null, "true"]);
  });

  it("не зависит от фильтров журнала", async () => {
    tx.get.mockResolvedValue(op({ id: 55 }));
    renderJournal("/transactions?tx=55");
    await screen.findByRole("region", { name: "Операция №55" });
    fireEvent.change(screen.getByDisplayValue("Все типы"), { target: { value: "income" } });
    await waitFor(() => expect(tx.list).toHaveBeenLastCalledWith(expect.objectContaining({ type: "income" })));
    expect(screen.getByRole("region", { name: "Операция №55" })).toBeTruthy();
    expect(tx.get).toHaveBeenCalledTimes(1);
  });

  it("платёж по долгу: показывает долг и ссылку на него, без изменения и удаления", async () => {
    tx.get.mockResolvedValue(PAYMENT);
    renderJournal("/transactions?tx=77");
    const card = await screen.findByRole("region", { name: "Операция №77" });
    expect(await within(card).findByText("Платёж по долгу")).toBeTruthy();
    expect(within(card).getByText("«Банк»")).toBeTruthy();
    expect(within(card).getByRole("link", { name: /Открыть долг/ }).getAttribute("href")).toBe("/debts/3");
    expect(within(card).queryByRole("button", { name: "Изменить" })).toBeNull();
    expect(within(card).queryByRole("button", { name: "Удалить" })).toBeNull();
  });

  it("удалённая операция (404): понятное сообщение, параметр в адресе остаётся до закрытия", async () => {
    tx.get.mockRejectedValue(apiError(404, "Операция не найдена"));
    renderJournal("/transactions?tx=77");
    const card = await screen.findByRole("region", { name: "Операция №77" });
    expect(await within(card).findByText("Операция №77 не найдена — возможно, она была удалена.")).toBeTruthy();
    expect(location()).toBe("/transactions?tx=77");
    expect(within(card).queryByRole("button", { name: "Изменить" })).toBeNull();

    fireEvent.click(within(card).getByRole("button", { name: "Закрыть карточку операции" }));
    expect(location()).toBe("/transactions");
    expect(screen.queryByRole("region", { name: /Операция №/ })).toBeNull();
  });

  it("сбой загрузки: повтор, параметр не снимается", async () => {
    tx.get.mockRejectedValueOnce(apiError(0, "offline")).mockResolvedValueOnce(op({ id: 55 }));
    renderJournal("/transactions?tx=55");
    const card = await screen.findByRole("region", { name: "Операция №55" });
    const error = await within(card).findByRole("alert");
    expect(error.textContent).toContain("Не удалось загрузить операцию №55");
    expect(location()).toBe("/transactions?tx=55");
    fireEvent.click(within(error).getByRole("button", { name: "Повторить" }));
    expect(await within(card).findByRole("button", { name: "Изменить" })).toBeTruthy();
    expect(tx.get).toHaveBeenCalledTimes(2);
  });

  it.each(["abc", "0", "-5", "1.5"])("некорректная ссылка tx=%s — без запроса", async (raw) => {
    renderJournal(`/transactions?tx=${raw}`);
    expect(await screen.findByText(/Некорректная ссылка на операцию/)).toBeTruthy();
    expect(tx.get).not.toHaveBeenCalled();
  });

  it("удаление выбранной операции закрывает карточку без «не найдена»", async () => {
    tx.get.mockResolvedValue(op({ id: 55 }));
    tx.remove.mockResolvedValue(undefined);
    renderJournal("/transactions?tx=55");
    const card = await screen.findByRole("region", { name: "Операция №55" });
    fireEvent.click(await within(card).findByRole("button", { name: "Удалить" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Удалить" }));
    await waitFor(() => expect(location()).toBe("/transactions"));
    expect(tx.remove).toHaveBeenCalledWith(55);
    expect(screen.queryByText(/не найдена/)).toBeNull();
    expect(tx.get).toHaveBeenCalledTimes(1);
  });
});
