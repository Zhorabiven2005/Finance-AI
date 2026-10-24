import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Category } from "@/lib/api/categories";
import { apiError, deferred, renderWithProviders } from "@/test/render";

import { CategoriesPage } from "./CategoriesPage";

const api = vi.hoisted(() => ({ list: vi.fn(), update: vi.fn(), remove: vi.fn(), create: vi.fn() }));
vi.mock("@/lib/api/categories", () => ({ categoriesApi: api }));

const cat = (over: Partial<Category>): Category => ({
  id: 1,
  name: "Продукты",
  type: "expense",
  icon: null,
  parent_id: null,
  is_default: true,
  is_archived: false,
  ...over,
});
const HOBBY = cat({ id: 40, name: "Хобби", is_default: false });

let nativeAlert: ReturnType<typeof vi.spyOn>;
let nativeConfirm: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.list.mockResolvedValue([cat({}), HOBBY]);
  nativeAlert = vi.spyOn(window, "alert").mockImplementation(() => {});
  nativeConfirm = vi.spyOn(window, "confirm").mockImplementation(() => true);
});

afterEach(() => {
  expect(nativeAlert).not.toHaveBeenCalled();
  expect(nativeConfirm).not.toHaveBeenCalled();
  vi.restoreAllMocks();
});

describe("Категории", () => {
  it("кнопки-иконки подписаны, базовую категорию удалить нельзя", async () => {
    renderWithProviders(<CategoriesPage />);
    expect(await screen.findByRole("button", { name: "Изменить категорию «Продукты»" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Архивировать категорию «Продукты»" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Удалить категорию «Продукты»" })).toBeNull();
    expect(screen.getByRole("button", { name: "Удалить категорию «Хобби»" })).toBeTruthy();
  });

  it("удаление: отмена ничего не меняет, подтверждение удаляет один раз", async () => {
    api.remove.mockResolvedValue(undefined);
    renderWithProviders(<CategoriesPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Удалить категорию «Хобби»" }));
    const dialog = screen.getByRole("dialog", { name: "Удалить категорию «Хобби»?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Отмена" }));
    expect(api.remove).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Удалить категорию «Хобби»" }));
    api.list.mockResolvedValue([cat({})]);
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Удалить" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(api.remove).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByText("Хобби")).toBeNull());
  });

  it("ошибка удаления видна в окне и не закрывает его", async () => {
    api.remove.mockRejectedValue(apiError(400, "Категория используется в операциях — удаление запрещено."));
    renderWithProviders(<CategoriesPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Удалить категорию «Хобби»" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Удалить" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain("используется в операциях");
    expect(screen.getByText("Хобби")).toBeTruthy();
  });

  it("ошибка архивирования — окно приложения; кнопка заблокирована на время запроса", async () => {
    const pending = deferred<Category>();
    api.update.mockReturnValue(pending.promise);
    renderWithProviders(<CategoriesPage />);
    const archive = (await screen.findByRole("button", { name: "Архивировать категорию «Хобби»" })) as HTMLButtonElement;
    fireEvent.click(archive);
    await waitFor(() => expect(archive.disabled).toBe(true));
    fireEvent.click(archive);
    expect(api.update).toHaveBeenCalledTimes(1);
    expect(api.update).toHaveBeenCalledWith(40, { is_archived: true });
    pending.reject(apiError(400, "Нельзя архивировать"));
    expect(await screen.findByRole("dialog", { name: "Не удалось изменить категорию" })).toBeTruthy();
  });

  it("ошибка загрузки с повтором", async () => {
    api.list.mockRejectedValueOnce(apiError(0, "нет связи")).mockResolvedValueOnce([HOBBY]);
    renderWithProviders(<CategoriesPage />);
    fireEvent.click(within(await screen.findByRole("alert")).getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText("Хобби")).toBeTruthy();
  });
});
