import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { EmptyState, LoadError } from "@/components/ui/Card";
import { errorMessage } from "@/lib/api/client";
import { goalsApi, type Goal, type GoalEntryType } from "@/lib/api/goals";

import { GoalCard } from "./GoalCard";
import { GoalEntryModal } from "./GoalEntryModal";
import { GoalFormModal } from "./GoalFormModal";

export function GoalsPage() {
  const queryClient = useQueryClient();
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Goal | null>(null);
  const [entryTarget, setEntryTarget] = useState<{ goal: Goal; type: GoalEntryType } | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [deleting, setDeleting] = useState<Goal | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ title: string; text: string } | null>(null);

  const {
    data: goals,
    isPending,
    isError,
    isFetching,
    refetch,
  } = useQuery({ queryKey: ["goals"], queryFn: () => goalsApi.list() });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["goals"] });

  const toggleArchive = useMutation({
    mutationFn: (g: Goal) => goalsApi.update(g.id, { is_archived: g.status !== "archived" }),
    onSuccess: invalidate,
    onError: (err) => setNotice({ title: "Не удалось изменить цель", text: errorMessage(err) }),
  });

  const remove = useMutation({
    mutationFn: (g: Goal) => goalsApi.remove(g.id),
    onSuccess: () => {
      setDeleting(null);
      invalidate();
    },
    onError: (err) => setDeleteError(errorMessage(err, "Не удалось удалить цель")),
  });

  const active = (goals ?? []).filter((g) => g.status !== "archived");
  const archived = (goals ?? []).filter((g) => g.status === "archived");

  const renderGrid = (list: Goal[]) => (
    <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
      {list.map((g) => (
        <GoalCard
          key={g.id}
          goal={g}
          onContribute={() => setEntryTarget({ goal: g, type: "contribution" })}
          onWithdraw={() => setEntryTarget({ goal: g, type: "withdrawal" })}
          onEdit={() => {
            setEditing(g);
            setFormOpen(true);
          }}
          archiving={toggleArchive.isPending && toggleArchive.variables?.id === g.id}
          onToggleArchive={() => toggleArchive.mutate(g)}
          onDelete={() => {
            setDeleteError(null);
            setDeleting(g);
          }}
        />
      ))}
    </div>
  );

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-[28px] font-semibold tracking-tight text-ink-900">Цели</h1>
        <Button
          onClick={() => {
            setEditing(null);
            setFormOpen(true);
          }}
        >
          + Новая цель
        </Button>
      </div>

      {isPending ? (
        <p className="text-[15px] text-ink-500">Загрузка…</p>
      ) : isError ? (
        <LoadError onRetry={() => refetch()} retrying={isFetching} />
      ) : active.length === 0 ? (
        <EmptyState>Финансовых целей пока нет — добавьте первую.</EmptyState>
      ) : (
        renderGrid(active)
      )}

      {archived.length > 0 && (
        <div className="flex flex-col gap-4">
          <button
            type="button"
            onClick={() => setShowArchived((v) => !v)}
            className="self-start text-sm font-medium text-accent hover:underline"
          >
            {showArchived ? "Скрыть архивные" : `Показать архивные (${archived.length})`}
          </button>
          {showArchived && renderGrid(archived)}
        </div>
      )}

      {formOpen && (
        <GoalFormModal
          goal={editing}
          onClose={() => setFormOpen(false)}
          onSaved={() => {
            setFormOpen(false);
            invalidate();
          }}
        />
      )}
      {deleting && (
        <ConfirmModal
          title={`Удалить цель «${deleting.name}»?`}
          confirmLabel="Удалить"
          pending={remove.isPending}
          error={deleteError}
          onConfirm={() => remove.mutate(deleting)}
          onClose={() => setDeleting(null)}
        >
          <p>Все накопления по этой цели также будут удалены. Это действие нельзя отменить.</p>
        </ConfirmModal>
      )}
      {notice && (
        <ConfirmModal title={notice.title} onClose={() => setNotice(null)}>
          {notice.text}
        </ConfirmModal>
      )}
      {entryTarget && (
        <GoalEntryModal
          goal={entryTarget.goal}
          type={entryTarget.type}
          onClose={() => setEntryTarget(null)}
          onSaved={() => {
            setEntryTarget(null);
            invalidate();
          }}
        />
      )}
    </div>
  );
}
