import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { FormField, Input, Select } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { categoriesApi, type Category, type CategoryType } from "@/lib/api/categories";
import { errorMessage, FormError } from "@/lib/api/client";
import { CATEGORY_ICON_REGISTRY } from "@/lib/categoryIcons";

import { CategoryIconPicker } from "./CategoryIconPicker";

export function CategoryFormModal({
  category,
  onClose,
  onSaved,
}: {
  category?: Category | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = category != null;
  const [name, setName] = useState(category?.name ?? "");
  const [type, setType] = useState<CategoryType>(category?.type ?? "expense");
  const [parentId, setParentId] = useState<string>(
    category?.parent_id != null ? String(category.parent_id) : "",
  );
  // Старые эмодзи из seed в реестре не найдутся — для них показываем
  // автоподбор и не трогаем сохранённое значение, пока иконку не меняли.
  const [icon, setIcon] = useState<string | null>(
    category?.icon && category.icon in CATEGORY_ICON_REGISTRY ? category.icon : null,
  );
  const [iconTouched, setIconTouched] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: allCategories } = useQuery({
    queryKey: ["categories", "all-for-parent-picker"],
    queryFn: () => categoriesApi.list({ includeArchived: true }),
  });

  // Родителем может быть только категория того же типа, без своего родителя
  // (глубина ограничена одним уровнем) и не сама редактируемая категория.
  const parentOptions = (allCategories ?? []).filter(
    (c) => c.type === type && c.parent_id === null && c.id !== category?.id && !c.is_archived,
  );

  const save = useMutation({
    mutationFn: async () => {
      if (!name.trim()) throw new FormError("Укажите название категории");
      const parent_id = parentId ? Number(parentId) : null;
      if (isEdit) {
        return categoriesApi.update(category.id, {
          name: name.trim(),
          type,
          parent_id,
          ...(iconTouched ? { icon } : {}),
        });
      }
      return categoriesApi.create({ name: name.trim(), type, icon, parent_id });
    },
    onSuccess: onSaved,
    onError: (err) => setError(errorMessage(err, "Не удалось сохранить категорию")),
  });

  return (
    <Modal title={isEdit ? "Изменить категорию" : "Своя категория"} onClose={onClose}>
      <form
        className="flex flex-col gap-5"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          save.mutate();
        }}
      >
        <FormField label="Тип">
          <Select
            value={type}
            onChange={(e) => {
              setType(e.target.value as CategoryType);
              setParentId("");
            }}
          >
            <option value="expense">Расход</option>
            <option value="income">Доход</option>
          </Select>
        </FormField>

        <FormField label="Название">
          <div className="flex items-center gap-3">
            <CategoryIconPicker
              value={icon}
              onChange={(next) => {
                setIcon(next);
                setIconTouched(true);
              }}
              name={name}
              type={type}
            />
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={100}
              placeholder="Например, «Хобби»"
              autoFocus
              className="flex-1"
            />
          </div>
        </FormField>

        <FormField label="Родительская категория (необязательно)">
          <Select value={parentId} onChange={(e) => setParentId(e.target.value)}>
            <option value="">Без родителя</option>
            {parentOptions.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </FormField>

        {error && <p className="text-sm text-danger">{error}</p>}

        <div className="mt-2 flex justify-end gap-3">
          <Button type="button" variant="secondary" onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" disabled={save.isPending}>
            Сохранить
          </Button>
        </div>
      </form>
    </Modal>
  );
}
