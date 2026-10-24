import { Archive, ArchiveRestore, CheckCircle2, Pencil, Target, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import type { Goal } from "@/lib/api/goals";
import { formatMoney } from "@/lib/money";

const STATUS_BADGE: Record<Goal["status"], { label: string; tone: "warn" | "ok" | "neutral" }> = {
  active: { label: "В процессе", tone: "warn" },
  completed: { label: "Достигнута", tone: "ok" },
  archived: { label: "В архиве", tone: "neutral" },
};

const BAR_CLASS: Record<Goal["status"], string> = {
  active: "bg-accent",
  completed: "bg-success",
  archived: "bg-ink-400",
};

function formatDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("ru-RU");
}

export function GoalCard({
  goal,
  onContribute,
  onWithdraw,
  onEdit,
  archiving = false,
  onToggleArchive,
  onDelete,
}: {
  goal: Goal;
  onContribute: () => void;
  onWithdraw: () => void;
  onEdit: () => void;
  archiving?: boolean;
  onToggleArchive: () => void;
  onDelete: () => void;
}) {
  const badge = STATUS_BADGE[goal.status];
  const completed = goal.status === "completed";

  return (
    <Card className={completed ? "border-success/30 bg-success-soft/30" : ""}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${
              completed ? "bg-success-soft text-success" : "bg-surface-hover text-ink-500"
            }`}
          >
            {completed ? (
              <CheckCircle2 className="h-4 w-4" strokeWidth={1.75} />
            ) : (
              <Target className="h-4 w-4" strokeWidth={1.75} />
            )}
          </div>
          <div className="min-w-0">
            <p className="truncate text-[17px] font-medium text-ink-900">{goal.name}</p>
            {goal.target_date && (
              <p className="text-sm text-ink-500">до {formatDate(goal.target_date)}</p>
            )}
          </div>
        </div>
        <Badge tone={badge.tone}>{badge.label}</Badge>
      </div>

      {goal.description && <p className="mt-3 text-sm text-ink-500">{goal.description}</p>}

      <div className="mt-4">
        <div className="flex items-baseline justify-between">
          <span className="tabular text-lg font-semibold text-ink-900">
            {formatMoney(goal.saved)}
          </span>
          <span className="text-sm text-ink-500">из {formatMoney(goal.target)}</span>
        </div>
        <div className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-surface-hover">
          <div
            className={`h-full rounded-full transition-all ${BAR_CLASS[goal.status]}`}
            style={{ width: `${Math.min(100, Math.max(0, goal.progress_percent))}%` }}
          />
        </div>
        <div className="mt-2 flex items-center justify-between text-sm text-ink-500">
          <span>Осталось {formatMoney(goal.remaining)}</span>
          <span className="tabular font-medium text-ink-900">{goal.progress_percent}%</span>
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="sm" onClick={onContribute}>
          Пополнить
        </Button>
        <Button variant="secondary" size="sm" onClick={onWithdraw} disabled={goal.saved.minor === 0}>
          Списать
        </Button>
        <Button variant="ghost" size="sm" onClick={onEdit} aria-label="Редактировать" title="Редактировать">
          <Pencil className="h-3.5 w-3.5" strokeWidth={1.75} />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={onToggleArchive}
          disabled={archiving}
          aria-label={goal.status === "archived" ? "Вернуть из архива" : "В архив"}
          title={goal.status === "archived" ? "Вернуть из архива" : "В архив"}
        >
          {goal.status === "archived" ? (
            <ArchiveRestore className="h-3.5 w-3.5" strokeWidth={1.75} />
          ) : (
            <Archive className="h-3.5 w-3.5" strokeWidth={1.75} />
          )}
        </Button>
        <Button
          variant="danger"
          size="sm"
          onClick={onDelete}
          aria-label="Удалить цель"
          title="Удалить цель"
        >
          <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />
          Удалить
        </Button>
      </div>
    </Card>
  );
}
