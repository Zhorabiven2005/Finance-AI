import { RotateCw } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <section
      className={cn(
        "rounded-2xl border border-border bg-surface p-6 shadow-[0_1px_2px_rgba(16,24,40,0.04)]",
        className,
      )}
    >
      {children}
    </section>
  );
}

export function CardHeader({
  title,
  action,
}: {
  title: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="mb-5 flex items-center justify-between gap-3">
      <h2 className="text-lg font-semibold tracking-tight text-ink-900">{title}</h2>
      {action}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="py-8 text-center text-[15px] text-ink-500">{children}</p>;
}

/** Ошибка загрузки списка — отдельно от пустого состояния: «пока нет данных»
 * при недоступном backend вводит в заблуждение. */
export function LoadError({
  onRetry,
  retrying = false,
  children = "Не удалось загрузить данные. Проверьте, что backend запущен.",
}: {
  onRetry: () => void;
  retrying?: boolean;
  children?: ReactNode;
}) {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 py-8 text-center">
      <p className="text-[15px] text-danger">{children}</p>
      <Button type="button" variant="secondary" size="sm" onClick={onRetry} disabled={retrying}>
        <RotateCw className={cn("h-3.5 w-3.5", retrying && "animate-spin")} strokeWidth={1.75} />
        Повторить
      </Button>
    </div>
  );
}
