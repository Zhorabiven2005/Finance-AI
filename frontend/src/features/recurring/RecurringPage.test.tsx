import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiError, deferred, renderWithProviders, rub } from "@/test/render";

import { RecurringPage } from "./RecurringPage";

const api = vi.hoisted(() => ({
  list: vi.fn(),
  process: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
}));

vi.mock("@/lib/api/recurringTransactions", () => ({ recurringTransactionsApi: api }));

describe("Recurring «Обработать сейчас»", () => {
  beforeEach(() => {
    for (const fn of Object.values(api)) fn.mockReset();
  });

  it("shows an in-app dialog (not a native alert) when nothing is created", async () => {
    api.list.mockResolvedValue([]);
    api.process.mockResolvedValue({ created_transactions: 0 });
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});

    renderWithProviders(<RecurringPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Обработать сейчас/ }));

    expect(await screen.findByText("Новых операций нет — все правила уже обработаны.")).toBeTruthy();
    expect(screen.getByText("Обработка завершена")).toBeTruthy();
    expect(alertSpy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Понятно" }));
    expect(screen.queryByText("Обработка завершена")).toBeNull();
  });

  it("reports the number of created operations in the dialog", async () => {
    api.list.mockResolvedValue([]);
    api.process.mockResolvedValue({ created_transactions: 3 });
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});

    renderWithProviders(<RecurringPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Обработать сейчас/ }));

    expect(await screen.findByText("Создано операций: 3")).toBeTruthy();
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("each click goes to the idempotent endpoint; repeated runs do not alert", async () => {
    api.list.mockResolvedValue([]);
    api.process.mockResolvedValueOnce({ created_transactions: 1 }).mockResolvedValueOnce({ created_transactions: 0 });
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});

    renderWithProviders(<RecurringPage />);
    const button = await screen.findByRole("button", { name: /Обработать сейчас/ });
    fireEvent.click(button);
    await screen.findByText("Создано операций: 1");
    fireEvent.click(screen.getByRole("button", { name: "Понятно" }));
    fireEvent.click(button);
    await screen.findByText("Новых операций нет — все правила уже обработаны.");
    await waitFor(() => expect(api.process).toHaveBeenCalledTimes(2));
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("shows errors in the dialog as well", async () => {
    api.list.mockResolvedValue([]);
    api.process.mockRejectedValue(new Error("boom"));
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});

    renderWithProviders(<RecurringPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Обработать сейчас/ }));

    expect(await screen.findByText("Не удалось выполнить действие")).toBeTruthy();
    expect(alertSpy).not.toHaveBeenCalled();
  });
});

const RULE = {
  id: 3,
  type: "expense",
  account_id: 1,
  account_name: "Сбер",
  category_id: 2,
  category_name: "Подписки",
  category_icon: null,
  amount: rub(35_000),
  comment: null,
  start_date: "2026-10-01",
  end_date: null,
  frequency: "monthly",
  next_run_date: "2026-11-01",
  is_active: true,
};

describe("Recurring rule deletion", () => {
  beforeEach(() => {
    for (const fn of Object.values(api)) fn.mockReset();
    api.list.mockResolvedValue([RULE]);
  });

  it("asks in an app dialog; cancel keeps the rule; confirm deletes once", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockImplementation(() => true);
    api.remove.mockResolvedValue(undefined);
    renderWithProviders(<RecurringPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Удалить" }));
    const dialog = screen.getByRole("dialog", { name: "Удалить регулярную операцию «Подписки»?" });
    expect(within(dialog).getByText(/Уже созданные останутся в журнале/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Отмена" }));
    expect(api.remove).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Удалить" }));
    api.list.mockResolvedValue([]);
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Удалить" }));
    expect(await screen.findByText("Регулярных операций пока нет.")).toBeTruthy();
    expect(api.remove).toHaveBeenCalledTimes(1);
    expect(api.remove).toHaveBeenCalledWith(3);
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it("a failed delete keeps the dialog open with the error and allows retry", async () => {
    const pending = deferred();
    api.remove.mockReturnValueOnce(pending.promise).mockResolvedValueOnce(undefined);
    renderWithProviders(<RecurringPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Удалить" }));
    const dialog = screen.getByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Удалить" }) as HTMLButtonElement;
    fireEvent.click(confirm);
    await waitFor(() => expect(confirm.disabled).toBe(true));
    fireEvent.click(confirm);
    expect(api.remove).toHaveBeenCalledTimes(1);
    pending.reject(apiError(500, "Ошибка базы данных"));
    expect((await within(dialog).findByRole("alert")).textContent).toBe("Ошибка базы данных");
    await waitFor(() => expect(confirm.disabled).toBe(false));
    fireEvent.click(confirm);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(api.remove).toHaveBeenCalledTimes(2);
  });

  it("stop/resume is locked while its request is pending", async () => {
    const pending = deferred();
    api.update.mockReturnValue(pending.promise);
    renderWithProviders(<RecurringPage />);
    const stop = (await screen.findByRole("button", { name: "Остановить" })) as HTMLButtonElement;
    fireEvent.click(stop);
    await waitFor(() => expect(stop.disabled).toBe(true));
    fireEvent.click(stop);
    expect(api.update).toHaveBeenCalledTimes(1);
    pending.resolve();
  });
});
