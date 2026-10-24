import { api } from "@/lib/api/client";

export type NotificationType =
  | "debt_due"
  | "debt_overdue"
  | "budget_warning"
  | "budget_exceeded"
  | "spending_increased"
  | "recurring_transaction_due"
  | "recurring_transaction_missed"
  | "system";

export type NotificationSeverity = "info" | "warning" | "danger";
export type NotificationEntityType = "debt" | "budget" | "recurring_transaction" | "analytics";

export interface AppNotification {
  id: number;
  type: NotificationType;
  severity: NotificationSeverity;
  title: string;
  message: string;
  entity_type: NotificationEntityType | null;
  entity_id: number | null;
  entity_exists: boolean;
  dedup_key: string;
  data: Record<string, unknown> | null;
  created_at: string;
  read_at: string | null;
  resolved_at: string | null;
  is_read: boolean;
  /** false — условие больше не выполняется (долг погашен, бюджет в норме). */
  is_active: boolean;
}

export interface NotificationCheckResult {
  created: number;
  resolved: number;
  reactivated: number;
  purged: number;
}

export const notificationsApi = {
  list: (status: "all" | "unread" = "all") =>
    api.get<AppNotification[]>(`/notifications?status=${status}`),
  unreadCount: () => api.get<{ unread: number }>("/notifications/unread-count"),
  markRead: (id: number) => api.post<AppNotification>(`/notifications/${id}/read`, {}),
  markAllRead: () => api.post<{ unread: number }>("/notifications/read-all", {}),
  remove: (id: number) => api.delete<void>(`/notifications/${id}`),
  check: () => api.post<NotificationCheckResult>("/notifications/check", {}),
};

/** Куда ведёт уведомление. null — связанной сущности нет (или удалена). */
export function notificationLink(n: AppNotification): string | null {
  if (!n.entity_exists) return null;
  switch (n.entity_type) {
    case "debt":
      return n.entity_id ? `/debts/${n.entity_id}` : "/debts";
    case "budget":
      return "/budgets";
    case "recurring_transaction":
      return "/recurring";
    case "analytics":
      return "/analytics";
    default:
      return null;
  }
}
