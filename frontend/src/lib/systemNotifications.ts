/**
 * Системные уведомления Windows через Web Notifications API браузера.
 *
 * Работают, только пока открыта вкладка приложения (в том числе свёрнутая).
 * Закрыта вкладка, остановлен backend, компьютер спит — системных уведомлений
 * нет; всё накапливается в центре уведомлений и будет видно там.
 *
 * Настройка и множество уже показанных id хранятся в localStorage: это
 * удобство конкретного браузера (разрешение браузера тоже действует только
 * для него). Дедупликация — по МНОЖЕСТВУ недавно показанных id, плюс
 * tag = dedup_key на уровне ОС.
 */

import type { AppNotification } from "@/lib/api/notifications";

const ENABLED_KEY = "finance-ai:system-notifications:enabled";
const SHOWN_KEY = "finance-ai:system-notifications:shown";
export const MAX_REMEMBERED_IDS = 500;
export const SETTINGS_CHANGED_EVENT = "finance-ai:system-notifications-changed";

export type PermissionState = "unsupported" | NotificationPermission;

function storage(): Storage | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

export function systemNotificationsSupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

export function permissionState(): PermissionState {
  return systemNotificationsSupported() ? Notification.permission : "unsupported";
}

export function isEnabled(): boolean {
  try {
    return storage()?.getItem(ENABLED_KEY) === "1";
  } catch {
    return false;
  }
}

export function setEnabled(value: boolean): void {
  try {
    storage()?.setItem(ENABLED_KEY, value ? "1" : "0");
  } catch {
    /* недоступное хранилище — настройка просто не запомнится */
  }
  window.dispatchEvent(new Event(SETTINGS_CHANGED_EVENT));
}

export function shownIds(): Set<number> {
  try {
    const raw = storage()?.getItem(SHOWN_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(parsed) ? parsed.filter((x): x is number => typeof x === "number") : []);
  } catch {
    return new Set();
  }
}

export function rememberShown(ids: Iterable<number>): void {
  const merged = [...shownIds(), ...ids];
  // Храним только последние MAX_REMEMBERED_IDS: id растут, старые больше не придут.
  const unique = [...new Set(merged)].sort((a, b) => a - b).slice(-MAX_REMEMBERED_IDS);
  try {
    storage()?.setItem(SHOWN_KEY, JSON.stringify(unique));
  } catch {
    /* см. setEnabled */
  }
}

/** Уведомления, которые ещё не показывались как системные. */
export function pendingForSystem(items: AppNotification[]): AppNotification[] {
  const shown = shownIds();
  return items.filter((n) => !n.is_read && n.is_active && !shown.has(n.id));
}

export function showSystemNotification(
  n: Pick<AppNotification, "id" | "title" | "message"> & { dedup_key?: string },
  onClick?: () => void,
): boolean {
  if (permissionState() !== "granted") return false;
  try {
    const notification = new Notification(n.title, {
      body: n.message,
      tag: n.dedup_key ?? `finance-ai-${n.id}`,
    });
    if (onClick) {
      notification.onclick = () => {
        window.focus();
        onClick();
        notification.close();
      };
    }
    return true;
  } catch {
    return false;
  }
}

/** Показывает новые уведомления и запоминает их; возвращает число показанных. */
export function deliverSystemNotifications(
  items: AppNotification[],
  onClick: (n: AppNotification) => void,
): number {
  if (!isEnabled() || permissionState() !== "granted") return 0;
  const pending = pendingForSystem(items);
  // Помечаем ДО показа: повторный опрос во время показа не задвоит.
  rememberShown(pending.map((n) => n.id));
  let shown = 0;
  for (const n of pending.slice(0, 5)) {
    if (showSystemNotification(n, () => onClick(n))) shown += 1;
  }
  return shown;
}
