import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiError, deferred, renderWithProviders } from "@/test/render";

import { NotificationsPage } from "./NotificationsPage";

const api = vi.hoisted(() => ({
  list: vi.fn(),
  unreadCount: vi.fn(),
  markRead: vi.fn(),
  markAllRead: vi.fn(),
  remove: vi.fn(),
  check: vi.fn(),
}));

vi.mock("@/lib/api/notifications", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/api/notifications")>();
  return { ...real, notificationsApi: api };
});

function note(over: Record<string, unknown>) {
  return {
    id: 1,
    type: "debt_overdue",
    severity: "danger",
    title: "Долг просрочен",
    message: "Долг «Банк»: срок был 01.10.2026.",
    entity_type: "debt",
    entity_id: 7,
    entity_exists: true,
    dedup_key: "debt_overdue:7:2026-10-01",
    data: null,
    created_at: "2026-10-15T09:00:00Z",
    read_at: null,
    resolved_at: null,
    is_read: false,
    is_active: true,
    ...over,
  };
}

const ITEMS = [
  note({}),
  note({ id: 2, type: "budget_warning", severity: "warning", title: "Бюджет почти исчерпан", entity_type: "budget", entity_id: 3, dedup_key: "b" }),
  note({ id: 3, type: "debt_due", severity: "info", title: "Скоро срок долга", is_read: true, read_at: "2026-10-15T10:00:00Z", entity_exists: false, dedup_key: "c" }),
  note({ id: 4, type: "budget_warning", title: "Старое", is_active: false, resolved_at: "2026-10-15T11:00:00Z", dedup_key: "d" }),
];

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.list.mockImplementation(async (status: string) =>
    status === "unread" ? ITEMS.filter((n) => !n.is_read && n.is_active) : ITEMS,
  );
  api.markRead.mockResolvedValue({});
  api.markAllRead.mockResolvedValue({ unread: 0 });
  api.remove.mockResolvedValue(undefined);
});

describe("Центр уведомлений", () => {
  it("показывает список и отличает непрочитанные, прочитанные и неактуальные", async () => {
    renderWithProviders(<NotificationsPage />);
    const rows = await screen.findAllByTestId("notification");
    expect(rows).toHaveLength(4);
    expect(rows.map((r) => r.getAttribute("data-unread"))).toEqual(["true", "true", "false", "false"]);
    expect(within(rows[3]!).getByText("Неактуально")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Непрочитанные (2)" })).toBeTruthy();
  });

  it("пустое состояние", async () => {
    api.list.mockResolvedValue([]);
    renderWithProviders(<NotificationsPage />);
    expect(await screen.findByText(/Уведомлений пока нет/)).toBeTruthy();
  });

  it("фильтр «Непрочитанные» запрашивает только непрочитанные", async () => {
    renderWithProviders(<NotificationsPage />);
    fireEvent.click(await screen.findByRole("tab", { name: /Непрочитанные/ }));
    await waitFor(() => expect(screen.getAllByTestId("notification")).toHaveLength(2));
  });

  it("отметить одно прочитанным", async () => {
    renderWithProviders(<NotificationsPage />);
    const [first] = await screen.findAllByTestId("notification");
    fireEvent.click(within(first!).getByRole("button", { name: "Прочитано" }));
    await waitFor(() => expect(api.markRead).toHaveBeenCalledWith(1));
  });

  it("прочитать все", async () => {
    renderWithProviders(<NotificationsPage />);
    await screen.findAllByTestId("notification");
    fireEvent.click(screen.getByRole("button", { name: /Прочитать все/ }));
    await waitFor(() => expect(api.markAllRead).toHaveBeenCalledTimes(1));
  });

  it("удаление — без нативного confirm", async () => {
    const confirmSpy = vi.spyOn(window, "confirm");
    renderWithProviders(<NotificationsPage />);
    const rows = await screen.findAllByTestId("notification");
    fireEvent.click(within(rows[1]!).getByRole("button", { name: "Удалить уведомление" }));
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith(2));
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it("переход к связанной сущности, только если она существует", async () => {
    renderWithProviders(<NotificationsPage />);
    const rows = await screen.findAllByTestId("notification");
    expect(within(rows[0]!).getByRole("link", { name: "Открыть" }).getAttribute("href")).toBe("/debts/7");
    expect(within(rows[1]!).getByRole("link", { name: "Открыть" }).getAttribute("href")).toBe("/budgets");
    expect(within(rows[2]!).queryByRole("link", { name: "Открыть" })).toBeNull();
    fireEvent.click(within(rows[0]!).getByRole("link", { name: "Открыть" }));
    await waitFor(() => expect(api.markRead).toHaveBeenCalledWith(1));
  });

  it("ручная проверка показывает результат в окне приложения", async () => {
    api.check.mockResolvedValue({ created: 0, resolved: 0, reactivated: 0, purged: 0 });
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});
    renderWithProviders(<NotificationsPage />);
    fireEvent.click(screen.getByRole("button", { name: /Проверить сейчас/ }));
    expect(await screen.findByText("Новых уведомлений нет.")).toBeTruthy();
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("пока удаление идёт, кнопки строки заблокированы — повторного запроса нет", async () => {
    const pending = deferred();
    api.remove.mockReturnValue(pending.promise);
    renderWithProviders(<NotificationsPage />);
    const rows = await screen.findAllByTestId("notification");
    const del = within(rows[0]!).getByRole("button", { name: "Удалить уведомление" }) as HTMLButtonElement;
    fireEvent.click(del);
    await waitFor(() => expect(del.disabled).toBe(true));
    fireEvent.click(del);
    expect((within(rows[0]!).getByRole("button", { name: "Прочитано" }) as HTMLButtonElement).disabled).toBe(true);
    expect((within(rows[1]!).getByRole("button", { name: "Удалить уведомление" }) as HTMLButtonElement).disabled).toBe(false);
    expect(api.remove).toHaveBeenCalledTimes(1);
    pending.resolve();
  });

  it("ошибка загрузки ленты — отдельное состояние с повтором", async () => {
    api.list.mockRejectedValueOnce(apiError(0, "offline"));
    renderWithProviders(<NotificationsPage />);
    const error = await screen.findByRole("alert");
    expect(screen.queryByText(/Уведомлений пока нет/)).toBeNull();
    fireEvent.click(within(error).getByRole("button", { name: "Повторить" }));
    expect(await screen.findAllByTestId("notification")).toHaveLength(4);
  });
});
