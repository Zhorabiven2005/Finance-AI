import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Account } from "@/lib/api/accounts";
import type { Transaction } from "@/lib/api/transactions";
import { apiError, renderWithProviders, rub } from "@/test/render";

import { TransactionPurposeModal } from "./TransactionPurposeModal";
import { TransactionsPage } from "./TransactionsPage";

const tx = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  remove: vi.fn(),
  update: vi.fn(),
  create: vi.fn(),
  setPurpose: vi.fn(),
  pairCandidates: vi.fn(),
}));
vi.mock("@/lib/api/transactions", () => ({ transactionsApi: tx }));
vi.mock("@/lib/api/transfers", () => ({ transfersApi: { list: async () => [], remove: vi.fn(), create: vi.fn() } }));
vi.mock("@/lib/api/debts", () => ({
  debtsApi: {
    list: async () => [
      { id: 5, counterparty_name: "Кредитка Т-Банк", direction: "i_owe", principal: rub(100), paid: rub(0), remaining: rub(100) },
      { id: 6, counterparty_name: "Друг должен мне", direction: "owed_to_me", principal: rub(100), paid: rub(0), remaining: rub(100) },
      { id: 7, counterparty_name: "Долларовый", direction: "i_owe", principal: { minor: 100, currency: "USD" }, paid: { minor: 0, currency: "USD" }, remaining: { minor: 100, currency: "USD" } },
    ],
  },
}));
const ACCOUNTS: Account[] = [
  { id: 1, name: "Т-банк", type: "bank", currency: "RUB", initial_balance_minor: 0, is_active: true, balance: rub(0) },
  { id: 2, name: "Сбербанк", type: "bank", currency: "RUB", initial_balance_minor: 0, is_active: true, balance: rub(0) },
  { id: 3, name: "Доллары", type: "bank", currency: "USD", initial_balance_minor: 0, is_active: true, balance: { minor: 0, currency: "USD" } },
];
vi.mock("@/lib/api/accounts", () => ({ accountsApi: { list: async () => ACCOUNTS } }));
vi.mock("@/lib/api/categories", () => ({
  categoriesApi: {
    list: async () => [
      { id: 10, name: "Прочие расходы", type: "expense", icon: null, parent_id: null, is_default: true, is_archived: false },
      { id: 20, name: "Прочие доходы", type: "income", icon: null, parent_id: null, is_default: true, is_archived: false },
    ],
  },
}));

function op(over: Partial<Transaction> = {}): Transaction {
  return {
    id: 1,
    account_id: 1,
    category_id: 10,
    type: "expense",
    amount: rub(1_808_906),
    occurred_at: "2026-10-05T10:19:00Z",
    comment: "Внутренний перевод на договор",
    debt_id: null,
    debt_name: null,
    purpose: null,
    purpose_account_id: null,
    purpose_debt_id: null,
    ...over,
  };
}

const accountName = (id: number) => ACCOUNTS.find((a) => a.id === id)?.name ?? `#${id}`;

function renderModal(t: Transaction = op()) {
  const onSaved = vi.fn();
  const onClose = vi.fn();
  renderWithProviders(
    <TransactionPurposeModal tx={t} accounts={ACCOUNTS} accountName={accountName} onClose={onClose} onSaved={onSaved} />,
  );
  return { onSaved, onClose };
}

const radio = (name: RegExp) => screen.getByRole("radio", { name });
const save = () => fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

beforeEach(() => {
  for (const fn of Object.values(tx)) fn.mockReset();
  tx.setPurpose.mockImplementation(async (id: number, input: object) => op({ id, ...input }));
  tx.pairCandidates.mockResolvedValue([]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Назначение операции", () => {
  it("для расхода — четыре варианта с объяснением влияния на показатели", () => {
    renderModal();
    const labels = screen.getAllByRole("radio").map((r) => r.closest("label")!.textContent);
    expect(labels).toHaveLength(4);
    expect(labels[0]).toContain("Обычный расход");
    expect(labels[1]).toContain("Перевод между своими счетами");
    expect(labels[2]).toContain("Перевод на свой внешний продукт");
    expect(labels[3]).toContain("Погашение долга или кредитки");
    expect(labels[3]).toContain("Не входит в расходы на жизнь");
    expect((radio(/Обычный расход/) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText(/Сумма, дата, счёт, категория и описание операции не меняются/)).toBeTruthy();
  });

  it("для дохода погашения долга нет", () => {
    renderModal(op({ type: "income", category_id: 20 }));
    expect(screen.getAllByRole("radio")).toHaveLength(3);
    expect(screen.getByText("Перевод со своего внешнего продукта")).toBeTruthy();
    expect(screen.queryByText(/Погашение долга/)).toBeNull();
  });

  it("перевод на свой внешний продукт сохраняется без лишних полей", async () => {
    const { onSaved, onClose } = renderModal();
    fireEvent.click(radio(/Перевод на свой внешний продукт/));
    save();
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(tx.setPurpose).toHaveBeenCalledWith(1, { purpose: "external_transfer", purpose_account_id: null, purpose_debt_id: null });
    expect(onClose).toHaveBeenCalled();
  });

  it("перевод между своими счетами требует второй счёт той же валюты", async () => {
    renderModal();
    fireEvent.click(radio(/Перевод между своими счетами/));
    const select = screen.getByLabelText("Второй свой счёт") as HTMLSelectElement;
    expect([...select.options].map((o) => o.textContent)).toEqual(["— выберите счёт —", "Сбербанк"]); // без самого счёта и USD
    save();
    expect(await screen.findByText("Выберите второй свой счёт, участвующий в переводе.")).toBeTruthy();
    expect(tx.setPurpose).not.toHaveBeenCalled();
    fireEvent.change(select, { target: { value: "2" } });
    save();
    await waitFor(() => expect(tx.setPurpose).toHaveBeenCalledWith(1, { purpose: "own_transfer", purpose_account_id: 2, purpose_debt_id: null }));
  });

  it("парная операция только предлагается; отмечается лишь по явному выбору", async () => {
    const pair = op({ id: 9, account_id: 2, type: "income", category_id: 20, comment: "Перевод себе" });
    tx.pairCandidates.mockResolvedValue([pair]);
    const first = renderModal();
    fireEvent.click(radio(/Перевод между своими счетами/));
    const box = await screen.findByTestId("pair-candidates");
    expect(box.textContent).toContain("не связывает операции само");
    fireEvent.change(screen.getByLabelText("Второй свой счёт"), { target: { value: "2" } });
    save();
    await waitFor(() => expect(first.onSaved).toHaveBeenCalled());
    expect(tx.setPurpose).toHaveBeenCalledTimes(1); // пара не отмечена автоматически
  });

  it("если пользователь отметил пару — вторая сторона тоже становится переводом", async () => {
    tx.pairCandidates.mockResolvedValue([op({ id: 9, account_id: 2, type: "income", category_id: 20 })]);
    const { onSaved } = renderModal();
    fireEvent.click(radio(/Перевод между своими счетами/));
    fireEvent.click(await screen.findByRole("checkbox", { name: /Отметить и её как перевод/ }));
    expect((screen.getByLabelText("Второй свой счёт") as HTMLSelectElement).value).toBe("2"); // подставлен из пары
    save();
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(tx.setPurpose).toHaveBeenNthCalledWith(1, 1, { purpose: "own_transfer", purpose_account_id: 2, purpose_debt_id: null });
    expect(tx.setPurpose).toHaveBeenNthCalledWith(2, 9, { purpose: "own_transfer", purpose_account_id: 1 });
  });

  it("погашение долга: долг необязателен, в списке только свои долги той же валюты", async () => {
    renderModal();
    fireEvent.click(radio(/Погашение долга/));
    const select = (await screen.findByLabelText("Какой долг погашает (необязательно)")) as HTMLSelectElement;
    await waitFor(() => expect(select.options.length).toBe(2));
    expect([...select.options].map((o) => o.textContent)).toEqual(["— не указывать —", "Кредитка Т-Банк"]);
    fireEvent.change(select, { target: { value: "5" } });
    save();
    await waitFor(() => expect(tx.setPurpose).toHaveBeenCalledWith(1, { purpose: "debt_repayment", purpose_account_id: null, purpose_debt_id: 5 }));
  });

  it("классификацию можно отменить — вернуть обычный тип", async () => {
    const { onSaved } = renderModal(op({ purpose: "external_transfer" }));
    expect((radio(/Перевод на свой внешний продукт/) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(radio(/Обычный расход/));
    save();
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(tx.setPurpose).toHaveBeenCalledWith(1, { purpose: null, purpose_account_id: null, purpose_debt_id: null });
  });

  it("ошибка backend показывается, окно остаётся открытым", async () => {
    tx.setPurpose.mockRejectedValue(apiError(422, "Второй счёт не найден"));
    const { onClose } = renderModal();
    fireEvent.click(radio(/Перевод на свой внешний продукт/));
    save();
    expect(await screen.findByText("Второй счёт не найден")).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("Назначение в журнале операций", () => {
  function renderJournal(route = "/transactions") {
    return renderWithProviders(
      <Routes>
        <Route path="/transactions" element={<TransactionsPage />} />
      </Routes>,
      { route },
    );
  }

  it("отмеченная операция видна с пометкой; обычная — без; кнопка открывает выбор", async () => {
    tx.list.mockResolvedValue({ data: [op({ id: 1, purpose: "external_transfer" }), op({ id: 2, comment: "Кафе" })], total: 2 });
    renderJournal();
    const rows = await screen.findAllByTestId("transaction-row");
    expect(within(rows[0]!).getByTestId("purpose-badge").textContent).toContain("Перевод на свой внешний продукт");
    expect(within(rows[0]!).getByTestId("purpose-badge").textContent).toContain("Не считается ни доходом, ни расходом");
    expect(within(rows[1]!).queryByTestId("purpose-badge")).toBeNull();
    // сумма и описание остаются прежними
    expect(rows[0]!.textContent).toMatch(/18\s089,06/);
    expect(rows[0]!.textContent).toContain("Внутренний перевод на договор");
    fireEvent.click(within(rows[1]!).getByRole("button", { name: "Назначение" }));
    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(screen.getByText("Назначение операции")).toBeTruthy();
  });

  it("платёж по долгу классифицировать нельзя — он управляется долгом", async () => {
    tx.list.mockResolvedValue({ data: [op({ id: 3, debt_id: 4, debt_name: "Банк" })], total: 1 });
    renderJournal();
    const row = (await screen.findAllByTestId("transaction-row"))[0]!;
    expect(within(row).queryByRole("button", { name: "Назначение" })).toBeNull();
  });

  it("карточка операции объясняет назначение и как его изменить", async () => {
    tx.list.mockResolvedValue({ data: [], total: 0 });
    tx.get.mockResolvedValue(op({ id: 5, purpose: "own_transfer", purpose_account_id: 2 }));
    renderJournal("/transactions?tx=5");
    const info = await screen.findByTestId("purpose-info");
    expect(info.textContent).toContain("Назначение: Перевод между своими счетами · второй счёт «Сбербанк»");
    expect(info.textContent).toContain("Отметку можно изменить или отменить");
  });

  it("на узком экране окно выбора прокручивается и не выходит за край", async () => {
    renderModal();
    const dialog = screen.getByRole("dialog");
    expect(dialog.className).toMatch(/max-w-2xl/);
    expect(dialog.className).toMatch(/overflow-y-auto/);
  });
});
