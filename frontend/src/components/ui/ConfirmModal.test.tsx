import { fireEvent, render, screen } from "@testing-library/react";
import { StrictMode, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ConfirmModal } from "./ConfirmModal";

function setup(props: Partial<Parameters<typeof ConfirmModal>[0]> = {}) {
  const onConfirm = vi.fn();
  const onClose = vi.fn();
  render(
    <ConfirmModal title="Удалить счёт «Сбер»?" onConfirm={onConfirm} onClose={onClose} {...props}>
      Описание действия
    </ConfirmModal>,
  );
  return { onConfirm, onClose };
}

describe("ConfirmModal", () => {
  it("в опасном подтверждении фокус на «Отмена», а не на «Удалить»", () => {
    setup();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Отмена" }));
  });

  it("в обычном подтверждении фокус на основном действии", () => {
    setup({ tone: "primary", confirmLabel: "Продолжить" });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Продолжить" }));
  });

  it.each([
    ["Отмена", () => fireEvent.click(screen.getByRole("button", { name: "Отмена" }))],
    ["крестик", () => fireEvent.click(screen.getByRole("button", { name: "Закрыть" }))],
    ["Escape", () => fireEvent.keyDown(document, { key: "Escape" })],
    ["клик по подложке", () => fireEvent.click(screen.getByRole("dialog").previousElementSibling!)],
  ])("%s закрывает окно без подтверждения", (_, act) => {
    const { onConfirm, onClose } = setup();
    act();
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("подтверждение вызывает onConfirm", () => {
    const { onConfirm } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Удалить" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("пока запрос идёт, кнопка подтверждения заблокирована и повторно не срабатывает", () => {
    const { onConfirm } = setup({ pending: true });
    const button = screen.getByRole("button", { name: "Удалить" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("показывает ошибку внутри окна", () => {
    setup({ error: "У счёта есть операции" });
    expect(screen.getByRole("alert").textContent).toBe("У счёта есть операции");
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it.each([
    ["обычный режим", false],
    ["React.StrictMode (как в main.tsx)", true],
  ])("после закрытия фокус возвращается к кнопке, открывшей окно — %s", (_, strict) => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Удалить строку
          </button>
          {open && <ConfirmModal title="Удалить?" onConfirm={() => {}} onClose={() => setOpen(false)} />}
        </>
      );
    }
    render(
      strict ? (
        <StrictMode>
          <Harness />
        </StrictMode>
      ) : (
        <Harness />
      ),
    );
    const opener = screen.getByRole("button", { name: "Удалить строку" });
    opener.focus();
    fireEvent.click(opener);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Отмена" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });
});
