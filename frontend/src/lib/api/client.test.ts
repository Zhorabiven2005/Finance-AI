import { describe, expect, it } from "vitest";

import { ApiError, errorMessage, FormError } from "./client";

describe("errorMessage", () => {
  it("текст проверки формы показывается как есть", () => {
    expect(errorMessage(new FormError("Некорректная сумма"), "Не удалось сохранить")).toBe("Некорректная сумма");
  });

  it("технические ошибки заменяются понятным текстом", () => {
    expect(errorMessage(new TypeError("x is undefined"), "Не удалось сохранить")).toBe("Не удалось сохранить");
  });

  it("detail из ответа backend", () => {
    expect(errorMessage(new ApiError("код 400", 400, "У счёта есть операции"))).toBe("У счёта есть операции");
    expect(errorMessage(new ApiError("код 422", 422, [{ msg: "поле обязательно" }]))).toBe("поле обязательно");
  });
});
