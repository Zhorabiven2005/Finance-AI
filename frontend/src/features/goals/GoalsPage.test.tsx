import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiError, deferred, renderWithProviders, rub } from "@/test/render";

import { GoalsPage } from "./GoalsPage";

const api = vi.hoisted(() => ({
  list: vi.fn(),
  remove: vi.fn(),
  update: vi.fn(),
}));

vi.mock("@/lib/api/goals", () => ({ goalsApi: api }));
vi.mock("@/lib/api/system", () => ({ systemApi: { currencies: async () => [] } }));

const goal = (over: Record<string, unknown>) => ({
  id: 1,
  name: "Игровой ПК",
  description: null,
  target: rub(10_000_000),
  saved: rub(2_000_000),
  remaining: rub(8_000_000),
  progress_percent: 20,
  currency: "RUB",
  target_date: null,
  status: "active",
  created_at: "2026-10-01T00:00:00Z",
  ...over,
});

describe("Goal deletion", () => {
  beforeEach(() => {
    for (const fn of Object.values(api)) fn.mockReset();
  });

  it("asks for confirmation in an app modal and does not delete on a single click", async () => {
    api.list.mockResolvedValue([goal({})]);
    api.remove.mockResolvedValue(undefined);
    const confirmSpy = vi.spyOn(window, "confirm");
    renderWithProviders(<GoalsPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Удалить цель" }));
    expect(screen.getByText("Удалить цель «Игровой ПК»?")).toBeTruthy();
    expect(screen.getByText(/Все накопления по этой цели также будут удалены/)).toBeTruthy();
    expect(api.remove).not.toHaveBeenCalled();
    expect(confirmSpy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(screen.queryByText("Удалить цель «Игровой ПК»?")).toBeNull();
    expect(api.remove).not.toHaveBeenCalled();
  });

  it("deletes after the user confirms", async () => {
    api.list.mockResolvedValue([goal({})]);
    api.remove.mockResolvedValue(undefined);
    renderWithProviders(<GoalsPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Удалить цель" }));
    const dialogButtons = screen.getAllByRole("button", { name: "Удалить" });
    fireEvent.click(dialogButtons[dialogButtons.length - 1]!);
    await waitFor(() => expect(api.remove).toHaveBeenCalledTimes(1));
    expect(api.remove.mock.calls[0]![0]).toBe(1);
  });

  it.each(["completed", "archived"])("delete is available for %s goals", async (status) => {
    api.list.mockResolvedValue([goal({ status })]);
    renderWithProviders(<GoalsPage />);
    if (status === "archived") fireEvent.click(await screen.findByText(/Показать архивные/));
    expect(await screen.findByRole("button", { name: "Удалить цель" })).toBeTruthy();
  });

  it("archive and delete are separate actions", async () => {
    api.list.mockResolvedValue([goal({})]);
    renderWithProviders(<GoalsPage />);
    expect(await screen.findByRole("button", { name: "В архив" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Удалить цель" })).toBeTruthy();
  });
});

describe("Goal archive toggle", () => {
  beforeEach(() => {
    for (const fn of Object.values(api)) fn.mockReset();
  });

  it("shows an API error in an app dialog (no native alert) and blocks repeat clicks while pending", async () => {
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});
    const pending = deferred();
    api.list.mockResolvedValue([goal({})]);
    api.update.mockReturnValue(pending.promise);
    renderWithProviders(<GoalsPage />);

    const archive = (await screen.findByRole("button", { name: "В архив" })) as HTMLButtonElement;
    fireEvent.click(archive);
    await waitFor(() => expect(archive.disabled).toBe(true));
    fireEvent.click(archive);
    expect(api.update).toHaveBeenCalledTimes(1);
    expect(api.update).toHaveBeenCalledWith(1, { is_archived: true });

    pending.reject(apiError(404, "Цель не найдена"));
    const dialog = await screen.findByRole("dialog", { name: "Не удалось изменить цель" });
    expect(within(dialog).getByText("Цель не найдена")).toBeTruthy();
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("a load error offers a retry instead of the empty state", async () => {
    api.list.mockRejectedValueOnce(apiError(0, "offline")).mockResolvedValueOnce([goal({})]);
    renderWithProviders(<GoalsPage />);
    const error = await screen.findByRole("alert");
    expect(screen.queryByText(/Финансовых целей пока нет/)).toBeNull();
    fireEvent.click(within(error).getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText("Игровой ПК")).toBeTruthy();
  });
});
