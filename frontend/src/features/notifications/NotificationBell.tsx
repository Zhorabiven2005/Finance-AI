import { useQuery } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { notificationLink, notificationsApi } from "@/lib/api/notifications";
import { cn } from "@/lib/cn";
import { SETTINGS_CHANGED_EVENT, deliverSystemNotifications, isEnabled } from "@/lib/systemNotifications";

// Лёгкий опрос (только чтение). Генерацию frontend не запускает — её делает
// backend при старте, по таймеру или по кнопке «Проверить сейчас».
export const NOTIFICATIONS_POLL_MS = 60_000;

export function NotificationBell() {
  const navigate = useNavigate();
  const { data } = useQuery({
    queryKey: ["notifications", "unread-count"],
    queryFn: notificationsApi.unreadCount,
    refetchInterval: NOTIFICATIONS_POLL_MS,
    refetchOnWindowFocus: true,
  });
  const unread = data?.unread ?? 0;

  // Список непрочитанных нужен только для системных уведомлений и только
  // когда они включены.
  const [systemEnabled, setSystemEnabled] = useState(isEnabled);
  useEffect(() => {
    const sync = () => setSystemEnabled(isEnabled());
    window.addEventListener(SETTINGS_CHANGED_EVENT, sync);
    return () => window.removeEventListener(SETTINGS_CHANGED_EVENT, sync);
  }, []);
  const { data: unreadItems } = useQuery({
    queryKey: ["notifications", "list", "unread"],
    queryFn: () => notificationsApi.list("unread"),
    refetchInterval: NOTIFICATIONS_POLL_MS,
    enabled: systemEnabled && unread > 0,
  });

  useEffect(() => {
    if (!unreadItems) return;
    deliverSystemNotifications(unreadItems, (n) => navigate(notificationLink(n) ?? "/notifications"));
  }, [unreadItems, navigate]);

  return (
    <NavLink
      to="/notifications"
      aria-label={unread ? `Уведомления: непрочитанных ${unread}` : "Уведомления"}
      title="Уведомления"
      className={({ isActive }) =>
        cn(
          "relative flex items-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors",
          isActive ? "bg-accent-soft text-accent" : "text-ink-500 hover:bg-surface-hover hover:text-ink-900",
        )
      }
    >
      <Bell className="h-4 w-4" strokeWidth={1.75} />
      Уведомления
      {unread > 0 && (
        <span
          data-testid="unread-badge"
          className="tabular inline-flex min-w-5 items-center justify-center rounded-full bg-danger px-1.5 text-xs font-semibold leading-5 text-white"
        >
          {unread > 99 ? "99+" : unread}
        </span>
      )}
    </NavLink>
  );
}
