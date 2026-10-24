import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertOctagon, AlertTriangle, BellRing, CheckCheck, Info, RefreshCw, Settings2, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader, EmptyState, LoadError } from "@/components/ui/Card";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { errorMessage } from "@/lib/api/client";
import { notificationLink, notificationsApi, type AppNotification } from "@/lib/api/notifications";
import { cn } from "@/lib/cn";
import {
  isEnabled,
  permissionState,
  rememberShown,
  setEnabled,
  showSystemNotification,
  type PermissionState,
} from "@/lib/systemNotifications";

const SEVERITY_ICON = {
  info: { Icon: Info, className: "bg-accent-soft text-accent" },
  warning: { Icon: AlertTriangle, className: "bg-warn-soft text-warn" },
  danger: { Icon: AlertOctagon, className: "bg-danger-soft text-danger" },
} as const;

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

const PERMISSION_TEXT: Record<PermissionState, string> = {
  unsupported: "Этот браузер не поддерживает системные уведомления.",
  default: "Браузер ещё не спрашивал разрешение.",
  granted: "Разрешение браузера получено.",
  denied: "Браузер запретил уведомления для этого сайта — разрешите их в настройках сайта в браузере.",
};

function SystemNotificationsSettings({ currentUnread }: { currentUnread: AppNotification[] }) {
  const [enabled, setEnabledState] = useState(isEnabled);
  const [permission, setPermission] = useState<PermissionState>(permissionState);
  const [hint, setHint] = useState<string | null>(null);

  const enable = async () => {
    let p = permissionState();
    if (p === "default") {
      p = await Notification.requestPermission();
      setPermission(p);
    }
    if (p !== "granted") {
      setHint(PERMISSION_TEXT[p]);
      return;
    }
    // Уже существующие уведомления не всплывают пачкой при включении —
    // системными становятся только новые.
    rememberShown(currentUnread.map((n) => n.id));
    setEnabled(true);
    setEnabledState(true);
    setHint(null);
  };

  const disable = () => {
    setEnabled(false);
    setEnabledState(false);
  };

  return (
    <Card>
      <CardHeader title="Системные уведомления Windows" />
      <div className="flex flex-col gap-4 text-[15px]">
        <p className="text-ink-500">
          Новые уведомления можно показывать во всплывающих окнах Windows. Они приходят, пока вкладка Finance AI
          открыта (можно свернуть) и запущен backend. Если вкладка закрыта или компьютер спит — уведомления
          накопятся здесь, в центре уведомлений.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          {enabled ? (
            <>
              <Badge tone="ok">Включены</Badge>
              <Button variant="secondary" size="sm" onClick={disable}>
                Выключить
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  setHint(
                    showSystemNotification({ id: 0, title: "Finance AI", message: "Системные уведомления работают." })
                      ? "Тестовое уведомление отправлено."
                      : "Не удалось показать уведомление — проверьте разрешение браузера и режим «Не беспокоить».",
                  )
                }
              >
                <BellRing className="h-4 w-4" strokeWidth={1.75} />
                Проверить показ
              </Button>
            </>
          ) : (
            <>
              <Badge tone="neutral">Выключены</Badge>
              <Button variant="secondary" size="sm" onClick={enable} disabled={permission === "unsupported"}>
                Включить
              </Button>
            </>
          )}
        </div>
        <p className="text-sm text-ink-500">{hint ?? PERMISSION_TEXT[permission]}</p>
      </div>
    </Card>
  );
}

export function NotificationsPage() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<"all" | "unread">("all");
  const [notice, setNotice] = useState<{ title: string; text: string } | null>(null);

  const { data: items, isPending, isError, isFetching, refetch } = useQuery({
    queryKey: ["notifications", "list", filter],
    queryFn: () => notificationsApi.list(filter),
  });
  const { data: unreadItems } = useQuery({
    queryKey: ["notifications", "list", "unread"],
    queryFn: () => notificationsApi.list("unread"),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["notifications"] });
  const fail = (err: unknown) => setNotice({ title: "Не удалось выполнить действие", text: errorMessage(err) });

  const markRead = useMutation({ mutationFn: (id: number) => notificationsApi.markRead(id), onSuccess: invalidate, onError: fail });
  const markAll = useMutation({ mutationFn: notificationsApi.markAllRead, onSuccess: invalidate, onError: fail });
  const remove = useMutation({ mutationFn: (id: number) => notificationsApi.remove(id), onSuccess: invalidate, onError: fail });
  const check = useMutation({
    mutationFn: notificationsApi.check,
    onSuccess: (r) => {
      invalidate();
      setNotice({
        title: "Проверка завершена",
        text: r.created ? `Новых уведомлений: ${r.created}.` : "Новых уведомлений нет.",
      });
    },
    onError: fail,
  });

  const unreadCount = unreadItems?.length ?? 0;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-[28px] font-semibold tracking-tight text-ink-900">Уведомления</h1>
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" onClick={() => check.mutate()} disabled={check.isPending}>
            <RefreshCw className="h-4 w-4" strokeWidth={1.75} />
            Проверить сейчас
          </Button>
          <Button variant="secondary" onClick={() => markAll.mutate()} disabled={unreadCount === 0 || markAll.isPending}>
            <CheckCheck className="h-4 w-4" strokeWidth={1.75} />
            Прочитать все
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader
          title="Лента"
          action={
            <div className="flex gap-1 rounded-lg border border-border bg-surface p-1" role="tablist">
              {(
                [
                  ["all", "Все"],
                  ["unread", `Непрочитанные${unreadCount ? ` (${unreadCount})` : ""}`],
                ] as const
              ).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={filter === key}
                  onClick={() => setFilter(key)}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-sm font-medium",
                    filter === key ? "bg-accent-soft text-accent" : "text-ink-500 hover:text-ink-900",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          }
        />
        {isPending ? (
          <p className="text-[15px] text-ink-500">Загрузка…</p>
        ) : isError ? (
          <LoadError onRetry={() => refetch()} retrying={isFetching} />
        ) : !items || items.length === 0 ? (
          <EmptyState>
            {filter === "unread" ? "Непрочитанных уведомлений нет." : "Уведомлений пока нет. Здесь появятся сроки долгов, бюджеты, рост расходов и регулярные операции."}
          </EmptyState>
        ) : (
          <ul className="divide-y divide-border">
            {items.map((n) => {
              const { Icon, className } = n.type === "system" ? { Icon: Settings2, className: "bg-surface-hover text-ink-500" } : SEVERITY_ICON[n.severity];
              const link = notificationLink(n);
              const unread = !n.is_read && n.is_active;
              const busy =
                (markRead.isPending && markRead.variables === n.id) ||
                (remove.isPending && remove.variables === n.id);
              return (
                <li
                  key={n.id}
                  data-testid="notification"
                  data-unread={unread}
                  className={cn("flex gap-4 py-4 first:pt-0 last:pb-0", !n.is_active && "opacity-60")}
                >
                  <div className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-full", className)}>
                    <Icon className="h-4 w-4" strokeWidth={1.75} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="flex flex-wrap items-center gap-2 text-[15px] font-medium text-ink-900">
                      {unread && <span className="h-2 w-2 rounded-full bg-accent" aria-label="Не прочитано" />}
                      {n.title}
                      {!n.is_active && <Badge tone="neutral">Неактуально</Badge>}
                    </p>
                    <p className="mt-0.5 text-[15px] text-ink-700">{n.message}</p>
                    <p className="mt-1 text-sm text-ink-400">{formatDateTime(n.created_at)}</p>
                  </div>
                  <div className="flex shrink-0 items-start gap-2">
                    {link && (
                      <Link
                        to={link}
                        onClick={() => !n.is_read && markRead.mutate(n.id)}
                        className="rounded-lg px-3 py-2 text-sm font-medium text-accent hover:bg-accent-soft"
                      >
                        Открыть
                      </Link>
                    )}
                    {!n.is_read && (
                      <Button variant="ghost" size="sm" disabled={busy} onClick={() => markRead.mutate(n.id)}>
                        Прочитано
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label="Удалить уведомление"
                      title="Удалить уведомление"
                      disabled={busy}
                      onClick={() => remove.mutate(n.id)}
                    >
                      <Trash2 className="h-4 w-4" strokeWidth={1.75} />
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      <SystemNotificationsSettings currentUnread={unreadItems ?? []} />

      {notice && (
        <ConfirmModal title={notice.title} onClose={() => setNotice(null)}>
          {notice.text}
        </ConfirmModal>
      )}
    </div>
  );
}
