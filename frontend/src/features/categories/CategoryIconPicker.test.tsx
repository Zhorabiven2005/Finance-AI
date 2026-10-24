import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CATEGORY_ICON_REGISTRY, iconForCategory } from "@/lib/categoryIcons";

import { CategoryIconPicker } from "./CategoryIconPicker";

function setup(value: string | null = null) {
  const onChange = vi.fn();
  render(<CategoryIconPicker value={value} onChange={onChange} name="Игры" type="expense" />);
  return onChange;
}

describe("CategoryIconPicker", () => {
  it("is a real, accessible button that opens a popover", () => {
    setup();
    const trigger = screen.getByRole("button", { name: "Выбрать иконку категории" });
    expect(trigger.tagName).toBe("BUTTON");
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("selecting a Lucide icon reports its key and closes the popover", () => {
    const onChange = setup();
    fireEvent.click(screen.getByRole("button", { name: "Выбрать иконку категории" }));
    fireEvent.click(screen.getByRole("button", { name: "gamepad-2" }));
    expect(onChange).toHaveBeenCalledWith("gamepad-2");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("marks the current icon as pressed and can reset to automatic", () => {
    const onChange = setup("car");
    fireEvent.click(screen.getByRole("button", { name: "Выбрать иконку категории" }));
    expect(screen.getByRole("button", { name: "car" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Подобрать автоматически" }));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("Escape closes the popover", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Выбрать иконку категории" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("offers a reasonable set of category icons", () => {
    expect(Object.keys(CATEGORY_ICON_REGISTRY).length).toBeGreaterThanOrEqual(30);
    for (const key of ["shopping-cart", "utensils", "house", "car", "dumbbell", "gamepad-2", "plane", "heart", "briefcase", "wallet"]) {
      expect(CATEGORY_ICON_REGISTRY[key]).toBeTruthy();
    }
  });
});

describe("iconForCategory", () => {
  it("prefers the chosen icon over the name-based one", () => {
    expect(iconForCategory("Продукты", "expense", "plane")).toBe(CATEGORY_ICON_REGISTRY["plane"]);
  });

  it("falls back to the name mapping for legacy emoji and null", () => {
    const byName = iconForCategory("Продукты", "expense");
    expect(iconForCategory("Продукты", "expense", "🛒")).toBe(byName);
    expect(iconForCategory("Продукты", "expense", null)).toBe(byName);
  });

  it("falls back to a neutral per-type icon for unknown custom categories", () => {
    expect(iconForCategory("Моя", "expense")).not.toBe(iconForCategory("Моя", "income"));
  });
});
