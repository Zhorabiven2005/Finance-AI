import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Change, CurrencyComparison, PeriodComparison } from "@/lib/api/insights";
import { renderWithProviders, rub } from "@/test/render";

import { ComparisonBlock } from "./ComparisonBlock";

const explainCalls = vi.hoisted(() => [] as unknown[][]);
vi.mock("@/lib/api/insights", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/insights")>()),
  streamInsightExplanation: async (...args: unknown[]) => {
    explainCalls.push(args);
  },
}));

function change(current: number, previous: number, percent: number | null, reason: Change["percent_null_reason"] = null): Change {
  return { current: rub(current), previous: rub(previous), delta: rub(current - previous), percent, percent_null_reason: reason };
}

function currency(over: Partial<CurrencyComparison> = {}): CurrencyComparison {
  return {
    currency: "RUB",
    confidence: "high",
    income: change(12_000_000, 10_000_000, 20),
    expense: change(9_000_000, 10_000_000, -10),
    net: change(3_000_000, 0, null, "zero_base"),
    debt_repayments: change(0, 0, null, "zero_base"),
    expense_without_debt_repayments: change(9_000_000, 10_000_000, -10),
    categories_up: [],
    categories_down: [],
    categories: [
      { category_id: 1, label: "Продукты", ...change(3_000_000, 1_000_000, 200) },
      { category_id: 2, label: "Транспорт", ...change(500_000, 0, null, "zero_base") },
      { category_id: 3, label: "Кафе и рестораны", ...change(1_000_000, 4_000_000, -75) },
    ],
    categories_truncated: false,
    large_expenses: { threshold: rub(330_000), current_count: 2, previous_count: 1, total: change(5_500_000, 2_000_000, 175) },
    large_expenses_null_reason: null,
    other_share: { current: 75, previous: 10, delta_points: 65 },
    transfers_excluded: { current_count: 3, current_total: rub(5_000_000), previous_count: 1, previous_total: rub(1_000_000) },
    possible_internal_pairs: { count: 0, total: rub(0) },
    summary: "Расходы снизились на 10 000,00 ₽ (-10,0%).",
    warnings: [],
    ...over,
  };
}

function comparison(over: Partial<PeriodComparison> = {}): PeriodComparison {
  return {
    key: "current_month",
    current: { date_from: "2026-10-01", date_to: "2026-10-25", label: "1–25 октября 2026", days: 25 },
    previous: { date_from: "2026-09-01", date_to: "2026-09-25", label: "1–25 сентября 2026", days: 25 },
    same_days: true,
    note: "Сравниваются одинаковые дни: 1–25 октября 2026 и 1–25 сентября 2026.",
    by_currency: [currency()],
    unavailable_reason: null,
    ...over,
  };
}

const render = (c: PeriodComparison = comparison(), canExplain = false) =>
  renderWithProviders(<ComparisonBlock comparison={c} period="current_month" canExplain={canExplain} />);

const tile = (label: string) => screen.getByText(label, { selector: "p" }).parentElement!;

describe("Сравнение периодов", () => {
  it("показывает, с каким периодом идёт сравнение", () => {
    render();
    const block = screen.getByTestId("comparison");
    expect(block.textContent).toContain("1–25 октября 2026 против 1–25 сентября 2026");
    expect(screen.getByText(/Сравниваются одинаковые дни/)).toBeTruthy();
    expect(screen.getByText("Сравнение надёжное")).toBeTruthy();
  });

  it("рост доходов и снижение расходов — хорошо; цвет и слова различаются", () => {
    render();
    const income = within(tile("Доходы")).getByTestId("change");
    expect(income.dataset.direction).toBe("up");
    expect(income.className).toContain("text-success");
    expect(income.textContent).toMatch(/\+20\s000,00\s₽ · больше/);
    expect(income.textContent).toContain("(+20,0%)");
    const expense = within(tile("Расходы на жизнь")).getByTestId("change");
    expect(expense.dataset.direction).toBe("down");
    expect(expense.className).toContain("text-success");
    expect(expense.textContent).toMatch(/−10\s000,00\s₽ · меньше/);
    expect(expense.textContent).toContain("(-10,0%)");
  });

  it("рост расходов — «внимание», без процента при нулевой базе", () => {
    render(comparison({ by_currency: [currency({ expense_without_debt_repayments: change(5_000_000, 0, null, "zero_base") })] }));
    const expense = within(tile("Расходы на жизнь")).getByTestId("change");
    expect(expense.className).toContain("text-warn");
    expect(expense.textContent).toContain("раньше было 0, процент не считается");
    expect(expense.textContent).not.toContain("%");
  });

  it("мало истории: процент не выводится, ограничения видны", () => {
    render(
      comparison({
        by_currency: [
          currency({
            confidence: "low",
            expense_without_debt_repayments: change(5_000_000, 100_000, null, "insufficient_history"),
            warnings: ["Операции в приложении есть только с 24.09.2026: 1–25 сентября 2026 покрыт данными частично."],
          }),
        ],
      }),
    );
    expect(screen.getByText("Сравнение ненадёжное")).toBeTruthy();
    const ch = within(tile("Расходы на жизнь")).getByTestId("change");
    expect(ch.textContent).toContain("(мало истории, процент не считается)");
    // разница без истории — не вывод: без цвета «хорошо/плохо»
    expect(ch.className).toContain("text-ink-500");
    expect(ch.dataset.neutral).toBe("true");
    expect(screen.getByTestId("comparison-warnings").textContent).toContain("покрыт данными частично");
  });

  it("подробности раскрываются по кнопке: категории, крупные расходы, переводы, «Прочие»", () => {
    render(comparison({ by_currency: [currency({ possible_internal_pairs: { count: 1, total: rub(1_000_000) } })] }));
    expect(screen.queryByTestId("comparison-details")).toBeNull();
    const toggle = screen.getByRole("button", { name: /Подробнее/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    const details = screen.getByTestId("comparison-details");
    expect(details.textContent).toContain("Продукты");
    expect(details.textContent).toContain("(+200,0%)");
    expect(details.textContent).toContain("Кафе и рестораны");
    expect(details.textContent).toContain("Крупные расходы");
    expect(details.textContent).toMatch(/2 шт\., было 1/);
    expect(details.textContent).toMatch(/Переводы между своими счетами: сейчас 3 на 50\s000,00\s₽/);
    expect(details.textContent).toContain("Возможные переводы, записанные как доход и расход: 1");
    expect(details.textContent).toContain("+65,0 п. п.");
    expect(details.textContent).not.toContain("Погашения долгов"); // погашений нет — строк нет
    expect(screen.getByRole("button", { name: /Скрыть подробности/ }).getAttribute("aria-expanded")).toBe("true");
  });

  it("основной показатель — расходы на жизнь без погашений; погашения отдельно", () => {
    render(
      comparison({
        by_currency: [
          currency({
            expense: change(9_000_000, 10_000_000, -10),
            debt_repayments: change(3_000_000, 0, null, "zero_base"),
            expense_without_debt_repayments: change(6_000_000, 10_000_000, -40),
          }),
        ],
      }),
    );
    // плитка показывает расходы на жизнь, а не все расходы с погашениями
    expect(tile("Расходы на жизнь").textContent).toMatch(/60\s000,00\s₽/);
    expect(tile("Расходы на жизнь").textContent).not.toMatch(/90\s000,00\s₽/);
    expect(tile("Доходы минус все расходы")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Подробнее/ }));
    const details = screen.getByTestId("comparison-details");
    expect(details.textContent).toContain("Погашения долгов (не входят в расходы на жизнь)");
    expect(details.textContent).toContain("Все расходы вместе с погашениями");
    expect(details.textContent).toMatch(/90\s000,00\s₽/);
  });

  it("нет данных ни в одном периоде", () => {
    render(comparison({ by_currency: [], unavailable_reason: "Ни в одном из двух периодов нет операций — сравнивать нечего." }));
    expect(screen.getByText(/сравнивать нечего/)).toBeTruthy();
    expect(screen.queryByTestId("comparison-currency")).toBeNull();
  });

  it("несколько валют — отдельные блоки, без общей суммы", () => {
    const usd = currency({ currency: "USD", income: { ...change(1, 1, 0), current: { minor: 100, currency: "USD" } } });
    render(comparison({ by_currency: [currency(), usd] }));
    expect(screen.getAllByTestId("comparison-currency")).toHaveLength(2);
    expect(screen.getByText("USD")).toBeTruthy();
  });

  it("недоверенные названия категорий — только текст", () => {
    const { container } = render(
      comparison({ by_currency: [currency({ categories: [{ category_id: 9, label: "<b>x</b><script>1</script>", ...change(100, 0, null, "zero_base") }] })] }),
    );
    fireEvent.click(screen.getByRole("button", { name: /Подробнее/ }));
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText("<b>x</b><script>1</script>")).toBeTruthy();
  });

  it("на узком экране плитки идут в одну колонку", () => {
    render();
    const grid = tile("Доходы").parentElement!;
    expect(grid.className).toContain("grid-cols-1");
    expect(grid.className).toContain("sm:grid-cols-3");
  });

  it("объяснение моделью: в запросе только id сравнения и период", async () => {
    render(comparison(), true);
    fireEvent.click(screen.getByRole("button", { name: /Объяснить/ }));
    await waitFor(() => expect(explainCalls).toHaveLength(1));
    expect(explainCalls[0]!.slice(0, 2)).toEqual(["comparison:RUB", "current_month"]);
  });

  it("без модели кнопки объяснения нет", () => {
    render(comparison(), false);
    expect(screen.queryByRole("button", { name: /Объяснить/ })).toBeNull();
  });
});
