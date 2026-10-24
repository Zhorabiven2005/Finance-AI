import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Budget } from "@/lib/api/budgets";
import { apiError, deferred, renderWithProviders, rub } from "@/test/render";

import { BudgetsPage } from "./BudgetsPage";

const api = vi.hoisted(() => ({ list: vi.fn(), remove: vi.fn(), create: vi.fn(), update: vi.fn() }));
vi.mock("@/lib/api/budgets", () => ({ budgetsApi: api }));

const FOOD: Budget = {
  id: 5,
  category_id: 1,
  category_name: "Продукты",
  category_icon: null,
  amount: rub(1_000_000),
  year: 2026,
  month: 10,
  spent: rub(900_000),
  remaining: rub(100_000),
  usage_percent: 90,
  status: "warning",
};

let nativeAlert: ReturnType<typeof vi.spyOn>;
let nativeConfirm: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.list.mockResolvedValue([FOOD]);
  nativeAlert = vi.spyOn(window, "alert").mockImplementation(() => {});
  nativeConfirm = vi.spyOn(window, "confirm").mockImplementation(() => true);
});

afterEach(() => {
  expect(nativeAlert).not.toHaveBeenCalled();
  expect(nativeConfirm).not.toHaveBeenCalled();
  vi.restoreAllMocks();
});

describe("Удаление бюджета", () => {
  it("отмена (Escape) не удаляет; подтверждение удаляет один раз и обновляет список", async () => {
    api.remove.mockResolvedValue(undefined);
    renderWithProviders(<BudgetsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Удалить" }));
    expect(within(screen.getByRole("dialog")).getByText(/Октябрь 2026/i)).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(api.remove).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Удалить" }));
    api.list.mockResolvedValue([]);
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Удалить" }));
    expect(await screen.findByText(/бюджетов ещё нет/)).toBeTruthy();
    expect(api.remove).toHaveBeenCalledTimes(1);
    expect(api.remove).toHaveBeenCalledWith(5);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("двойной клик во время запроса — один запрос; ошибка остаётся в окне", async () => {
    const pending = deferred();
    api.remove.mockReturnValue(pending.promise);
    renderWithProviders(<BudgetsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Удалить" }));
    const dialog = screen.getByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Удалить" }) as HTMLButtonElement;
    fireEvent.click(confirm);
    await waitFor(() => expect(confirm.disabled).toBe(true));
    fireEvent.click(confirm);
    expect(api.remove).toHaveBeenCalledTimes(1);
    pending.reject(apiError(404, "Бюджет не найден"));
    expect((await within(dialog).findByRole("alert")).textContent).toBe("Бюджет не найден");
    await waitFor(() => expect(confirm.disabled).toBe(false));
  });
});

it("ошибка загрузки бюджетов не выдаётся за пустой список", async () => {
  api.list.mockRejectedValue(apiError(500, "Internal Server Error"));
  renderWithProviders(<BudgetsPage />);
  expect((await screen.findByRole("alert")).textContent).toContain("Не удалось загрузить данные");
  expect(screen.queryByText(/бюджетов ещё нет/)).toBeNull();
});
