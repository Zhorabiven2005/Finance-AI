import { NavLink, Outlet } from "react-router-dom";
import {
  LayoutDashboard,
  Landmark,
  ArrowLeftRight,
  ChartColumn,
  HandCoins,
  Tags,
  PiggyBank,
  Repeat,
  Target,
  DatabaseBackup,
  Sparkles,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { NotificationBell } from "@/features/notifications/NotificationBell";
import { cn } from "@/lib/cn";

const NAV_ITEMS: { to: string; label: string; end?: boolean; icon: LucideIcon }[] = [
  { to: "/", label: "Дашборд", end: true, icon: LayoutDashboard },
  { to: "/accounts", label: "Счета", icon: Landmark },
  { to: "/transactions", label: "Операции", icon: ArrowLeftRight },
  { to: "/analytics", label: "Аналитика", icon: ChartColumn },
  { to: "/assistant", label: "Помощник", icon: Sparkles },
  { to: "/budgets", label: "Бюджеты", icon: PiggyBank },
  { to: "/goals", label: "Цели", icon: Target },
  { to: "/recurring", label: "Регулярные", icon: Repeat },
  { to: "/debts", label: "Долги", icon: HandCoins },
  { to: "/categories", label: "Категории", icon: Tags },
];

export function Layout() {
  return (
    <div className="min-h-screen bg-page">
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-8 gap-y-2 px-8 py-4">
          <span className="shrink-0 whitespace-nowrap text-lg font-semibold tracking-tight text-ink-900">
            Finance AI
          </span>
          <nav className="flex flex-wrap gap-1">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end ?? false}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-[15px] font-medium transition-colors",
                      isActive
                        ? "bg-accent-soft text-accent"
                        : "text-ink-500 hover:bg-surface-hover hover:text-ink-900",
                    )
                  }
                >
                  <Icon className="h-[18px] w-[18px]" strokeWidth={1.75} />
                  {item.label}
                </NavLink>
              );
            })}
          </nav>
          {/* Служебные разделы — отдельно от основной навигации, справа. */}
          <div className="ml-auto flex items-center gap-1">
            <NotificationBell />
          <NavLink
            to="/data"
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-accent-soft text-accent"
                  : "text-ink-500 hover:bg-surface-hover hover:text-ink-900",
              )
            }
          >
            <DatabaseBackup className="h-4 w-4" strokeWidth={1.75} />
            Импорт и экспорт
          </NavLink>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-8 py-10">
        <Outlet />
      </main>
    </div>
  );
}
