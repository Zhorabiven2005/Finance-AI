import { api } from "@/lib/api/client";

export type CategoryType = "income" | "expense";

export interface Category {
  id: number;
  name: string;
  type: CategoryType;
  icon: string | null;
  parent_id: number | null;
  is_default: boolean;
  is_archived: boolean;
}

export interface CategoryCreateInput {
  name: string;
  type: CategoryType;
  icon?: string | null;
  parent_id?: number | null;
}

export interface CategoryUpdateInput {
  name?: string;
  type?: CategoryType;
  icon?: string | null;
  parent_id?: number | null;
  is_archived?: boolean;
}

export const categoriesApi = {
  list: (options?: { type?: CategoryType; includeArchived?: boolean }) => {
    const params = new URLSearchParams();
    if (options?.type) params.set("type", options.type);
    if (options?.includeArchived) params.set("include_archived", "true");
    const qs = params.toString();
    return api.get<Category[]>(qs ? `/categories?${qs}` : "/categories");
  },
  create: (input: CategoryCreateInput) => api.post<Category>("/categories", input),
  update: (id: number, input: CategoryUpdateInput) =>
    api.patch<Category>(`/categories/${id}`, input),
  remove: (id: number) => api.delete<void>(`/categories/${id}`),
};
