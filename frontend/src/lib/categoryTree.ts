import type { Category } from "@/lib/api/categories";

/**
 * Упорядочивает категории для плоских списков выбора (select): родители в
 * алфавитном порядке, каждая подкатегория сразу после своего родителя.
 * Дерево ограничено одним уровнем (родитель → подкатегория, без внуков).
 */
export function orderCategoriesForSelect(categories: Category[]): Category[] {
  const parents = categories
    .filter((c) => c.parent_id === null)
    .sort((a, b) => a.name.localeCompare(b.name, "ru"));
  const childrenByParent = new Map<number, Category[]>();
  for (const c of categories) {
    if (c.parent_id === null) continue;
    const list = childrenByParent.get(c.parent_id) ?? [];
    list.push(c);
    childrenByParent.set(c.parent_id, list);
  }
  for (const list of childrenByParent.values()) {
    list.sort((a, b) => a.name.localeCompare(b.name, "ru"));
  }

  const result: Category[] = [];
  for (const parent of parents) {
    result.push(parent);
    result.push(...(childrenByParent.get(parent.id) ?? []));
  }
  // Подкатегории, чей родитель отфильтрован (например, по типу) — на всякий
  // случай не теряем их молча, добавляем в конец.
  const includedIds = new Set(result.map((c) => c.id));
  for (const c of categories) {
    if (!includedIds.has(c.id)) result.push(c);
  }
  return result;
}

export interface CategoryTreeNode {
  category: Category;
  children: Category[];
}

/** Группирует категории в дерево для страницы «Категории»: родители со
 * своими подкатегориями, плюс отдельная группа подкатегорий-сирот (родитель
 * удалён быть не может, пока используется, так что это только оборонительный
 * случай на будущее). */
export function buildCategoryTree(categories: Category[]): CategoryTreeNode[] {
  const byId = new Map(categories.map((c) => [c.id, c]));
  const childrenByParent = new Map<number, Category[]>();
  for (const c of categories) {
    if (c.parent_id === null) continue;
    const list = childrenByParent.get(c.parent_id) ?? [];
    list.push(c);
    childrenByParent.set(c.parent_id, list);
  }
  for (const list of childrenByParent.values()) {
    list.sort((a, b) => a.name.localeCompare(b.name, "ru"));
  }

  const nodes: CategoryTreeNode[] = categories
    .filter((c) => c.parent_id === null)
    .sort((a, b) => a.name.localeCompare(b.name, "ru"))
    .map((parent) => ({ category: parent, children: childrenByParent.get(parent.id) ?? [] }));

  for (const c of categories) {
    if (c.parent_id !== null && !byId.has(c.parent_id)) {
      nodes.push({ category: c, children: [] });
    }
  }
  return nodes;
}
