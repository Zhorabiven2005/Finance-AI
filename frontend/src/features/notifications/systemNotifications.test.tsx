import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AppNotification } from "@/lib/api/notifications";
import {
  MAX_REMEMBERED_IDS,
  deliverSystemNotifications,
  pendingForSystem,
  rememberShown,
  setEnabled,
  shownIds,
} from "@/lib/systemNotifications";
import { MemoryStorage, renderWithProviders } from "@/test/render";

import { NotificationBell } from "./NotificationBell";

const api = vi.hoisted(() => ({ unreadCount: vi.fn(), list: vi.fn() }));
vi.mock("@/lib/api/notifications", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/api/notifications")>();
  return { ...real, notificationsApi: api };
});

const shown: { title: string; tag: string | undefined }[] = [];

class FakeNotification {
  static permission: NotificationPermission = "granted";
  static requestPermission = vi.fn(async () => FakeNotification.permission);
  onclick: (() => void) | null = null;
  constructor(title: string, options?: NotificationOptions) {
    shown.push({ title, tag: options?.tag });
  }
  close() {}
}

function n(id: number, over: Partial<AppNotification> = {}): AppNotification {
  return {
    id,
    type: "debt_overdue",
    severity: "danger",
    title: `Уведомление ${id}`,
    message: "текст",
    entity_type: "debt",
    entity_id: 1,
    entity_exists: true,
    dedup_key: `key-${id}`,
    data: null,
    created_at: "2026-10-15T09:00:00Z",
    read_at: null,
    resolved_at: null,
    is_read: false,
    is_active: true,
    ...over,
  };
}

beforeEach(() => {
  vi.stubGlobal("localStorage", new MemoryStorage());
  shown.length = 0;
  FakeNotification.permission = "granted";
  vi.stubGlobal("Notification", FakeNotification);
  api.unreadCount.mockReset();
  api.list.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Системные уведомления (Web Notifications)", () => {
  it("выключены по умолчанию — ничего не показывается", () => {
    expect(deliverSystemNotifications([n(1)], () => {})).toBe(0);
    expect(shown).toEqual([]);
  });

  it("показывает новые один раз с tag = dedup_key", () => {
    setEnabled(true);
    expect(deliverSystemNotifications([n(1), n(2)], () => {})).toBe(2);
    expect(shown.map((s) => s.tag)).toEqual(["key-1", "key-2"]);
    expect(deliverSystemNotifications([n(1), n(2)], () => {})).toBe(0);
    expect(shown).toHaveLength(2);
  });

  it("дедупликация по множеству показанных id, а не только по последнему", () => {
    setEnabled(true);
    deliverSystemNotifications([n(5)], () => {});
    deliverSystemNotifications([n(9)], () => {});
    // Более старое (id=5) снова пришло после более нового (id=9) — не показываем.
    expect(deliverSystemNotifications([n(5), n(9), n(7)], () => {})).toBe(1);
    expect(shown.map((s) => s.title)).toEqual(["Уведомление 5", "Уведомление 9", "Уведомление 7"]);
  });

  it("прочитанные и неактуальные не показываются", () => {
    expect(pendingForSystem([n(1, { is_read: true }), n(2, { is_active: false }), n(3)]).map((x) => x.id)).toEqual([3]);
  });

  it("без разрешения браузера ничего не показывает и не запоминает", () => {
    setEnabled(true);
    FakeNotification.permission = "denied";
    expect(deliverSystemNotifications([n(1)], () => {})).toBe(0);
    expect(shownIds().size).toBe(0);
  });

  it("память показанных id ограничена", () => {
    rememberShown(Array.from({ length: MAX_REMEMBERED_IDS + 50 }, (_, i) => i + 1));
    const ids = shownIds();
    expect(ids.size).toBe(MAX_REMEMBERED_IDS);
    expect(ids.has(1)).toBe(false);
    expect(ids.has(MAX_REMEMBERED_IDS + 50)).toBe(true);
  });

  it("не больше 5 всплывающих за раз, остальные помечаются показанными", () => {
    setEnabled(true);
    expect(deliverSystemNotifications(Array.from({ length: 8 }, (_, i) => n(i + 1)), () => {})).toBe(5);
    expect(shownIds().size).toBe(8);
  });
});

describe("Индикатор непрочитанных", () => {
  it("показывает число непрочитанных", async () => {
    api.unreadCount.mockResolvedValue({ unread: 3 });
    renderWithProviders(<NotificationBell />);
    expect((await screen.findByTestId("unread-badge")).textContent).toBe("3");
    expect(screen.getByRole("link", { name: "Уведомления: непрочитанных 3" }).getAttribute("href")).toBe("/notifications");
  });

  it("без непрочитанных индикатора нет", async () => {
    api.unreadCount.mockResolvedValue({ unread: 0 });
    renderWithProviders(<NotificationBell />);
    await screen.findByRole("link", { name: "Уведомления" });
    expect(screen.queryByTestId("unread-badge")).toBeNull();
  });

  it("большие числа сокращаются", async () => {
    api.unreadCount.mockResolvedValue({ unread: 150 });
    renderWithProviders(<NotificationBell />);
    expect((await screen.findByTestId("unread-badge")).textContent).toBe("99+");
  });

  it("при включённых системных уведомлениях доставляет новые", async () => {
    setEnabled(true);
    api.unreadCount.mockResolvedValue({ unread: 1 });
    api.list.mockResolvedValue([n(42)]);
    renderWithProviders(<NotificationBell />);
    await vi.waitFor(() => expect(shown.map((s) => s.title)).toEqual(["Уведомление 42"]));
    expect(api.list).toHaveBeenCalledWith("unread");
  });
});
