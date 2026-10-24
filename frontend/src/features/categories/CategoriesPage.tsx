import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader, EmptyState, LoadError } from "@/components/ui/Card";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { categoriesApi, type Category } from "@/lib/api/categories";
import { errorMessage } from "@/lib/api/client";
import { CategoryIcon } from "@/lib/categoryIcons";
import { buildCategoryTree } from "@/lib/categoryTree";

import { CategoryFormModal } from "./CategoryFormModal";

function CategoryRow({
  category,
  indented,
  busy,
  onEdit,
  onToggleArchive,
  onDelete,
}: {
  category: Category;
  indented: boolean;
  busy: boolean;
  onEdit: (c: Category) => void;
  onToggleArchive: (c: Category) => void;
  onDelete: (c: Category) => void;
}) {
  return (
    <li
      className={`flex items-center gap-3 py-3.5 first:pt-0 last:pb-0 ${indented ? "pl-8" : ""}`}
    >
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-hover text-ink-500">
        <CategoryIcon name={category.name} type={category.type} icon={category.icon} />
      </div>
      <span className="flex min-w-0 flex-1 items-center gap-2 text-[15px] font-medium text-ink-900">
        <span className="truncate">{category.name}</span>
        {category.is_default && <Badge tone="neutral">базовая</Badge>}
        {category.is_archived && <Badge tone="warn">в архиве</Badge>}
      </span>
      <Button
        variant="secondary"
        size="sm"
        onClick={() => onEdit(category)}
        aria-label={`Изменить категорию «${category.name}»`}
        title="Изменить"
      >
        <Pencil className="h-3.5 w-3.5" strokeWidth={1.75} />
      </Button>
      <Button
        variant="secondary"
        size="sm"
        disabled={busy}
        onClick={() => onToggleArchive(category)}
        aria-label={
          category.is_archived
            ? `Вернуть категорию «${category.name}» из архива`
            : `Архивировать категорию «${category.name}»`
        }
        title={category.is_archived ? "Вернуть из архива" : "В архив"}
      >
        {category.is_archived ? (
          <ArchiveRestore className="h-3.5 w-3.5" strokeWidth={1.75} />
        ) : (
          <Archive className="h-3.5 w-3.5" strokeWidth={1.75} />
        )}
      </Button>
      {!category.is_default && (
        <Button
          variant="danger"
          size="sm"
          onClick={() => onDelete(category)}
          aria-label={`Удалить категорию «${category.name}»`}
          title="Удалить"
        >
          <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />
        </Button>
      )}
    </li>
  );
}

function CategoryGroup({
  categories,
  busyId,
  onEdit,
  onToggleArchive,
  onDelete,
}: {
  categories: Category[];
  busyId: number | null;
  onEdit: (c: Category) => void;
  onToggleArchive: (c: Category) => void;
  onDelete: (c: Category) => void;
}) {
  const tree = buildCategoryTree(categories);
  if (tree.length === 0) return <EmptyState>Категорий нет.</EmptyState>;
  return (
    <ul className="divide-y divide-border">
      {tree.map(({ category: parent, children }) => (
        <li key={parent.id}>
          <ul className={children.length > 0 ? "border-b border-border" : ""}>
            <CategoryRow
              category={parent}
              indented={false}
              busy={busyId === parent.id}
              onEdit={onEdit}
              onToggleArchive={onToggleArchive}
              onDelete={onDelete}
            />
            {children.map((child) => (
              <CategoryRow
                key={child.id}
                category={child}
                indented
                busy={busyId === child.id}
                onEdit={onEdit}
                onToggleArchive={onToggleArchive}
                onDelete={onDelete}
              />
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}

export function CategoriesPage() {
  const queryClient = useQueryClient();
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Category | null>(null);
  const [showArchived, setShowArchived] = useState(true);
  const [deleting, setDeleting] = useState<Category | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ title: string; text: string } | null>(null);

  const { data: categories, isPending, isError, isFetching, refetch } = useQuery({
    queryKey: ["categories", "all-including-archived"],
    queryFn: () => categoriesApi.list({ includeArchived: true }),
  });

  const toggleArchive = useMutation({
    mutationFn: (c: Category) => categoriesApi.update(c.id, { is_archived: !c.is_archived }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["categories"] }),
    onError: (err) => setNotice({ title: "Не удалось изменить категорию", text: errorMessage(err) }),
  });

  const remove = useMutation({
    mutationFn: (c: Category) => categoriesApi.remove(c.id),
    onSuccess: () => {
      setDeleting(null);
      queryClient.invalidateQueries({ queryKey: ["categories"] });
    },
    onError: (err) => setDeleteError(errorMessage(err, "Не удалось удалить категорию")),
  });
  const busyId = toggleArchive.isPending ? (toggleArchive.variables?.id ?? null) : null;
  const askDelete = (c: Category) => {
    setDeleteError(null);
    setDeleting(c);
  };

  const visible = (categories ?? []).filter((c) => showArchived || !c.is_archived);
  const income = visible.filter((c) => c.type === "income");
  const expense = visible.filter((c) => c.type === "expense");

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-[28px] font-semibold tracking-tight text-ink-900">Категории</h1>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-ink-500">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(e) => setShowArchived(e.target.checked)}
              className="h-4 w-4 rounded border-border"
            />
            Показывать архивные
          </label>
          <Button
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            + Своя категория
          </Button>
        </div>
      </div>

      {isPending ? (
        <p className="text-[15px] text-ink-500">Загрузка…</p>
      ) : isError ? (
        <Card>
          <LoadError onRetry={() => refetch()} retrying={isFetching} />
        </Card>
      ) : (
        <div className="grid gap-6 md:grid-cols-2">
          <Card>
            <CardHeader title="Доходы" />
            <CategoryGroup
              categories={income}
              onEdit={(c) => {
                setEditing(c);
                setFormOpen(true);
              }}
              busyId={busyId}
              onToggleArchive={(c) => toggleArchive.mutate(c)}
              onDelete={askDelete}
            />
          </Card>
          <Card>
            <CardHeader title="Расходы" />
            <CategoryGroup
              categories={expense}
              onEdit={(c) => {
                setEditing(c);
                setFormOpen(true);
              }}
              busyId={busyId}
              onToggleArchive={(c) => toggleArchive.mutate(c)}
              onDelete={askDelete}
            />
          </Card>
        </div>
      )}

      {deleting && (
        <ConfirmModal
          title={`Удалить категорию «${deleting.name}»?`}
          pending={remove.isPending}
          error={deleteError}
          onConfirm={() => remove.mutate(deleting)}
          onClose={() => setDeleting(null)}
        >
          <p>
            Удалить можно только категорию без операций, подкатегорий, бюджетов и регулярных
            операций. Если категория уже используется, архивируйте её: история сохранится.
          </p>
        </ConfirmModal>
      )}
      {notice && (
        <ConfirmModal title={notice.title} onClose={() => setNotice(null)}>
          {notice.text}
        </ConfirmModal>
      )}
      {formOpen && (
        <CategoryFormModal
          category={editing}
          onClose={() => setFormOpen(false)}
          onSaved={() => {
            setFormOpen(false);
            queryClient.invalidateQueries({ queryKey: ["categories"] });
          }}
        />
      )}
    </div>
  );
}
