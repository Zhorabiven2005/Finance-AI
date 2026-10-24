import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Account } from "@/lib/api/accounts";
import { apiError, deferred, renderWithProviders, rub } from "@/test/render";

import { AccountsPage } from "./AccountsPage";

const api = vi.hoisted(() => ({ list: vi.fn(), update: vi.fn(), remove: vi.fn(), create: vi.fn() }));
vi.mock("@/lib/api/accounts", () => ({ accountsApi: api }));

const SBER: Account = {
  id: 1,
  name: "Сбер",
  type: "bank",
  currency: "RUB",
  initial_balance_minor: 0,
  is_active: true,
  balance: rub(100_000),
};

let nativeAlert: ReturnType<typeof vi.spyOn>;
let nativeConfirm: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.list.mockResolvedValue([SBER]);
  nativeAlert = vi.spyOn(window, "alert").mockImplementation(() => {});
  nativeConfirm = vi.spyOn(window, "confirm").mockImplementation(() => true);
});

afterEach(() => {
  expect(nativeAlert).not.toHaveBeenCalled();
  expect(nativeConfirm).not.toHaveBeenCalled();
  vi.restoreAllMocks();
});

async function openDelete() {
  fireEvent.click(await screen.findByRole("button", { name: "Удалить" }));
  return screen.getByRole("dialog", { name: "Удалить счёт «Сбер»?" });
}

describe("Удаление счёта", () => {
  it("отмена ничего не удаляет", async () => {
    renderWithProviders(<AccountsPage />);
    const dialog = await openDelete();
    expect(within(dialog).getByText(/деактивируйте его/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Отмена" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(api.remove).not.toHaveBeenCalled();
  });

  it("после подтверждения удаляет один раз, закрывает окно и обновляет список", async () => {
    api.remove.mockResolvedValue(undefined);
    renderWithProviders(<AccountsPage />);
    const dialog = await openDelete();
    api.list.mockResolvedValue([]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Удалить" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(api.remove).toHaveBeenCalledTimes(1);
    expect(api.remove).toHaveBeenCalledWith(1);
    expect(await screen.findByText("Счетов пока нет — создайте первый.")).toBeTruthy();
  });

  it("ошибка backend видна в окне, окно остаётся открытым, действие можно повторить", async () => {
    api.remove
      .mockRejectedValueOnce(apiError(400, "У счёта есть операции — удаление запрещено."))
      .mockResolvedValueOnce(undefined);
    renderWithProviders(<AccountsPage />);
    const dialog = await openDelete();
    fireEvent.click(within(dialog).getByRole("button", { name: "Удалить" }));
    expect((await within(dialog).findByRole("alert")).textContent).toBe("У счёта есть операции — удаление запрещено.");
    expect(screen.getByRole("dialog")).toBe(dialog);
    const confirm = within(dialog).getByRole("button", { name: "Удалить" }) as HTMLButtonElement;
    await waitFor(() => expect(confirm.disabled).toBe(false));
    fireEvent.click(confirm);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(api.remove).toHaveBeenCalledTimes(2);
  });

  it("повторный клик во время запроса не отправляет второй запрос", async () => {
    const pending = deferred();
    api.remove.mockReturnValue(pending.promise);
    renderWithProviders(<AccountsPage />);
    const dialog = await openDelete();
    const confirm = within(dialog).getByRole("button", { name: "Удалить" }) as HTMLButtonElement;
    fireEvent.click(confirm);
    await waitFor(() => expect(confirm.disabled).toBe(true));
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(api.remove).toHaveBeenCalledTimes(1);
    pending.resolve();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

describe("Деактивация счёта", () => {
  it("ошибка показывается в окне приложения, кнопка заблокирована на время запроса", async () => {
    const pending = deferred<Account>();
    api.update.mockReturnValue(pending.promise);
    renderWithProviders(<AccountsPage />);
    const toggle = (await screen.findByRole("button", { name: "Деактивировать" })) as HTMLButtonElement;
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle.disabled).toBe(true));
    fireEvent.click(toggle);
    expect(api.update).toHaveBeenCalledTimes(1);
    pending.reject(apiError(400, "Счёт используется в регулярной операции"));
    const dialog = await screen.findByRole("dialog", { name: "Не удалось изменить счёт" });
    expect(within(dialog).getByText("Счёт используется в регулярной операции")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Понятно" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(toggle.disabled).toBe(false);
  });
});

describe("Ошибка загрузки списка", () => {
  it("показывает ошибку вместо «пусто» и позволяет повторить", async () => {
    api.list.mockRejectedValueOnce(apiError(0, "Backend недоступен")).mockResolvedValueOnce([SBER]);
    renderWithProviders(<AccountsPage />);
    const error = await screen.findByRole("alert");
    expect(error.textContent).toContain("Не удалось загрузить данные");
    expect(screen.queryByText(/Счетов пока нет/)).toBeNull();
    fireEvent.click(within(error).getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText("Сбер")).toBeTruthy();
    expect(api.list).toHaveBeenCalledTimes(2);
  });
});
