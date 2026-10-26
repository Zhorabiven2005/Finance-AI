import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FinancialWarning, WarningsResponse } from "@/lib/api/insights";
import { MemoryStorage, renderWithProviders, rub } from "@/test/render";

import { DISMISSED_STORAGE_KEY, VISIBLE_WARNINGS, WarningsSection } from "./WarningsSection";

function warning(over: Partial<FinancialWarning> = {}): FinancialWarning {
  return {
    key: "budget_exceeded:1:2026-10",
    type: "budget_exceeded",
    kind: "fact",
    severity: "warning",
    title: "Бюджет «Продукты» превышен",
    message: "Потрачено 12 000,00 ₽ при лимите 10 000,00 ₽ — больше на 2 000,00 ₽.",
    currency: "RUB",
    metrics: [
      { label: "Потрачено", money: rub(1_200_000) },
      { label: "Использовано", percent: 120 },
    ],
    period: { date_from: "2026-10-01", date_to: "2026-10-31", label: "октябрь 2026" },
    recommendation: "Посмотрите операции этой категории за месяц.",
    link: { to: "/budgets", label: "Бюджеты" },
    ...over,
  };
}

const pace = warning({
  key: "budget_pace_risk:2:2026-10",
  type: "budget_pace_risk",
  kind: "estimate",
  severity: "attention",
  title: "Бюджет «Кафе» может быть превышен",
  message: "Если тратить так же, к концу месяца выйдет около 12 400,00 ₽. Это оценка по темпу, а не факт.",
});

let payload: WarningsResponse | null;
let calls: number;
let storage: MemoryStorage;

beforeEach(() => {
  payload = { generated_at: "2026-10-15T00:00:00Z", today: "2026-10-15", warnings: [warning(), pace], limitations: [] };
  calls = 0;
  storage = new MemoryStorage();
  vi.stubGlobal("localStorage", storage);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/v1/insights/warnings") {
        calls += 1;
        if (!payload) return new Response(JSON.stringify({ detail: "Ошибка" }), { status: 500 });
        return new Response(JSON.stringify(payload), { status: 200 });
      }
      throw new Error(`unexpected fetch ${url}`);
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const items = () => screen.queryAllByTestId("warning");

describe("Финансовые предупреждения", () => {
  it("заголовок, причина, суммы, период, важность и рекомендация", async () => {
    renderWithProviders(<WarningsSection />);
    const first = (await screen.findAllByTestId("warning"))[0]!;
    const c = within(first);
    expect(c.getByText("Бюджет «Продукты» превышен")).toBeTruthy();
    expect(c.getByText("Важно")).toBeTruthy();
    expect(c.getByText("Факт")).toBeTruthy();
    expect(c.getByText("октябрь 2026 · RUB")).toBeTruthy();
    expect(first.textContent).toMatch(/12\s000,00\s₽/);
    expect(first.textContent).toContain("120,0%");
    expect(c.getByText("Посмотрите операции этой категории за месяц.")).toBeTruthy();
    expect(c.getByRole("link", { name: /Бюджеты/ }).getAttribute("href")).toBe("/budgets");
  });

  it("оценка отличается от факта и не помечена как «Важно»", async () => {
    renderWithProviders(<WarningsSection />);
    const second = (await screen.findAllByTestId("warning"))[1]!;
    expect(within(second).getByText("Оценка")).toBeTruthy();
    expect(within(second).queryByText("Важно")).toBeNull();
  });

  it("много предупреждений: сначала несколько, остальные по кнопке", async () => {
    payload!.warnings = Array.from({ length: 5 }, (_, i) =>
      warning({ key: `large_expense:${i}`, type: "large_expense", kind: "observation", severity: "attention", title: `Крупный расход ${i}` }),
    );
    renderWithProviders(<WarningsSection />);
    await waitFor(() => expect(items()).toHaveLength(VISIBLE_WARNINGS));
    fireEvent.click(screen.getByRole("button", { name: "Показать все (5)" }));
    expect(items()).toHaveLength(5);
  });

  it("пустое состояние и то, что проверить не удалось", async () => {
    payload = { ...payload!, warnings: [], limitations: ["Крупные расходы в RUB не проверялись: мало данных."] };
    renderWithProviders(<WarningsSection />);
    expect((await screen.findByTestId("warnings-empty")).textContent).toBe("Сейчас предупреждений нет.");
    expect(screen.getByText("Что не удалось проверить (1)")).toBeTruthy();
    expect(screen.getByText(/Крупные расходы в RUB не проверялись/)).toBeTruthy();
  });

  it("ошибка загрузки — сообщение и повтор", async () => {
    payload = null;
    renderWithProviders(<WarningsSection />);
    expect(await screen.findByText(/Не удалось проверить предупреждения/)).toBeTruthy();
    payload = { generated_at: "", today: "", warnings: [warning()], limitations: [] };
    fireEvent.click(screen.getByRole("button", { name: /Повторить/ }));
    await waitFor(() => expect(items()).toHaveLength(1));
  });

  it("скрытое предупреждение не возвращается после обновления страницы", async () => {
    const view = renderWithProviders(<WarningsSection />);
    const first = (await screen.findAllByTestId("warning"))[0]!;
    fireEvent.click(within(first).getByRole("button", { name: /Скрыть/ }));
    expect(items().map((x) => x.dataset.key)).toEqual(["budget_pace_risk:2:2026-10"]);
    expect(JSON.parse(storage.getItem(DISMISSED_STORAGE_KEY)!)).toEqual(["budget_exceeded:1:2026-10"]);
    view.unmount();

    renderWithProviders(<WarningsSection />);
    await waitFor(() => expect(items()).toHaveLength(1));
    expect(items()[0]!.dataset.key).toBe("budget_pace_risk:2:2026-10");
    // скрытое можно посмотреть и вернуть
    fireEvent.click(screen.getByRole("button", { name: "Скрытые предупреждения (1)" }));
    fireEvent.click(within(items()[1]!).getByRole("button", { name: /Вернуть/ }));
    await waitFor(() => expect(screen.queryByRole("button", { name: /Скрытые предупреждения/ })).toBeNull());
    expect(JSON.parse(storage.getItem(DISMISSED_STORAGE_KEY)!)).toEqual([]);
  });

  it("новое событие с другим ключом показывается, даже если похожее скрыто", async () => {
    storage.setItem(DISMISSED_STORAGE_KEY, JSON.stringify(["budget_exceeded:1:2026-09"]));
    renderWithProviders(<WarningsSection />);
    await waitFor(() => expect(items()).toHaveLength(2)); // октябрьский ключ другой — предупреждение видно
  });

  it("одинаковые предупреждения не множатся при повторных запросах", async () => {
    const view = renderWithProviders(<WarningsSection />);
    await waitFor(() => expect(items()).toHaveLength(2));
    view.unmount();
    renderWithProviders(<WarningsSection />);
    await waitFor(() => expect(items()).toHaveLength(2));
    expect(calls).toBe(2);
    expect(new Set(items().map((x) => x.dataset.key)).size).toBe(2);
  });

  it("недоступное хранилище не ломает раздел", async () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    });
    renderWithProviders(<WarningsSection />);
    const first = (await screen.findAllByTestId("warning"))[0]!;
    fireEvent.click(within(first).getByRole("button", { name: /Скрыть/ }));
    expect(items()).toHaveLength(1);
  });

  it("недоверенные названия — только текст; на узком экране одна колонка", async () => {
    payload!.warnings = [warning({ title: "Бюджет «<img src=x onerror=1>» превышен" })];
    const { container } = renderWithProviders(<WarningsSection />);
    await waitFor(() => expect(items()).toHaveLength(1));
    expect(container.querySelector("img")).toBeNull();
    const list = items()[0]!.parentElement!;
    expect(list.className).toContain("grid-cols-1");
    expect(items()[0]!.className).toContain("min-w-0");
  });
});

// --- сводка крупных расходов ------------------------------------------------------------------

function large(i: number, currency = "RUB"): FinancialWarning {
  return warning({
    key: `large_expense:${100 + i}`,
    type: "large_expense",
    kind: "observation",
    severity: "attention",
    title: `Крупный расход: ${i + 1} 000,00 ₽`,
    message: `«Прочие расходы», счёт «Т-банк», 0${i + 1}.10.2026. Это в ${i + 10} раза больше вашей обычной траты.`,
    currency,
    metrics: [],
    period: { date_from: "2026-10-01", date_to: "2026-10-01", label: `0${i + 1}.10.2026` },
    recommendation: "Если это перевод на свой счёт или погашение долга — оформите его переводом.",
    link: { to: "/transactions", label: "Операции" },
  });
}

function withGroup(n = 5) {
  const ops = Array.from({ length: n }, (_, i) => large(i));
  payload = {
    generated_at: "2026-10-15T00:00:00Z",
    today: "2026-10-15",
    warnings: [warning(), ...ops],
    limitations: [],
    large_expense_groups: [
      {
        currency: "RUB",
        count: n,
        total: rub(7_370_577),
        keys: ops.map((w) => w.key),
        period: { date_from: "2026-09-16", date_to: "2026-10-15", label: "последние 30 дней" },
      },
    ],
  };
  return ops;
}

const group = () => screen.getByTestId("warning-group");

describe("Финансовые предупреждения: сводка крупных расходов", () => {
  it("пять крупных расходов — одна компактная сводка с количеством и суммой", async () => {
    withGroup();
    renderWithProviders(<WarningsSection />);
    await waitFor(() => expect(screen.getAllByTestId("warning-group")).toHaveLength(1));
    // отдельных карточек для операций нет — только бюджет и сводка
    expect(items().map((x) => x.dataset.key)).toEqual(["budget_exceeded:1:2026-10"]);
    expect(screen.getByText("Актуальных: 2")).toBeTruthy();
    expect(group().textContent).toMatch(/Крупные расходы: 5 операций на 73\s705,77\s₽/);
    expect(group().textContent).toContain("последние 30 дней · RUB");
    expect(group().textContent).toContain("не обязательно лишний расход");
    expect(group().textContent).toContain("назначение может быть неизвестно приложению");
    // рекомендация одна на сводку, а не пять раз
    expect(group().textContent!.split("оформите его переводом").length - 1).toBe(1);
  });

  it("список операций раскрывается и сворачивается", async () => {
    withGroup();
    renderWithProviders(<WarningsSection />);
    await waitFor(() => expect(screen.getByTestId("warning-group")).toBeTruthy());
    expect(screen.queryByTestId("warning-group-items")).toBeNull();
    const toggle = within(group()).getByRole("button", { name: "Показать операции (5)" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    const rows = screen.getAllByTestId("warning-group-item");
    expect(rows.map((r) => r.dataset.key)).toEqual(["large_expense:100", "large_expense:101", "large_expense:102", "large_expense:103", "large_expense:104"]);
    expect(rows[0]!.textContent).toContain("Крупный расход: 1 000,00 ₽");
    expect(rows[0]!.textContent).toContain("в 10 раза больше вашей обычной траты");
    expect(within(rows[0]!).getByRole("link", { name: /Операции/ }).getAttribute("href")).toBe("/transactions");
    fireEvent.click(within(group()).getByRole("button", { name: "Свернуть операции" }));
    expect(screen.queryByTestId("warning-group-items")).toBeNull();
  });

  it("операцию из сводки можно скрыть по её ключу и вернуть; сумма сводки не пересчитывается на клиенте", async () => {
    withGroup();
    renderWithProviders(<WarningsSection />);
    await waitFor(() => expect(screen.getByTestId("warning-group")).toBeTruthy());
    fireEvent.click(within(group()).getByRole("button", { name: /Показать операции/ }));
    fireEvent.click(within(screen.getAllByTestId("warning-group-item")[1]!).getByRole("button", { name: /Скрыть/ }));
    expect(JSON.parse(storage.getItem(DISMISSED_STORAGE_KEY)!)).toEqual(["large_expense:101"]);
    expect(screen.getAllByTestId("warning-group-item")).toHaveLength(4);
    expect(group().textContent).toContain("Из них скрыто: 1");
    expect(group().textContent).toMatch(/5 операций на 73\s705,77\s₽/); // сумма — из backend, как есть
    fireEvent.click(screen.getByRole("button", { name: "Скрытые предупреждения (1)" }));
    fireEvent.click(within(items().at(-1)!).getByRole("button", { name: /Вернуть/ }));
    await waitFor(() => expect(screen.getAllByTestId("warning-group-item")).toHaveLength(5));
  });

  it("«Скрыть все» скрывает операции сводки по их ключам; бюджет остаётся", async () => {
    const ops = withGroup();
    renderWithProviders(<WarningsSection />);
    await waitFor(() => expect(screen.getByTestId("warning-group")).toBeTruthy());
    fireEvent.click(within(group()).getByRole("button", { name: /Скрыть все/ }));
    expect(screen.queryByTestId("warning-group")).toBeNull();
    expect(JSON.parse(storage.getItem(DISMISSED_STORAGE_KEY)!).sort()).toEqual(ops.map((w) => w.key).sort());
    expect(items().map((x) => x.dataset.key)).toEqual(["budget_exceeded:1:2026-10"]);
    expect(screen.getByRole("button", { name: "Скрытые предупреждения (5)" })).toBeTruthy();
  });

  it("если скрыто всё — понятное пустое состояние", async () => {
    const ops = withGroup(2);
    payload!.warnings = ops;
    storage.setItem(DISMISSED_STORAGE_KEY, JSON.stringify(ops.map((w) => w.key)));
    renderWithProviders(<WarningsSection />);
    expect((await screen.findByTestId("warnings-empty")).textContent).toBe("Актуальных предупреждений нет — остальные вы скрыли.");
    expect(screen.queryByTestId("warning-group")).toBeNull();
  });

  it("разные валюты — отдельные сводки, суммы не складываются", async () => {
    const rubOps = [large(0), large(1)];
    const usdOps = [large(2, "USD")];
    payload = {
      generated_at: "",
      today: "",
      warnings: [...rubOps, ...usdOps],
      limitations: [],
      large_expense_groups: [
        { currency: "RUB", count: 2, total: rub(300_000), keys: rubOps.map((w) => w.key), period: { date_from: "", date_to: "", label: "последние 30 дней" } },
        { currency: "USD", count: 1, total: { minor: 90_000, currency: "USD" }, keys: usdOps.map((w) => w.key), period: { date_from: "", date_to: "", label: "последние 30 дней" } },
      ],
    };
    renderWithProviders(<WarningsSection />);
    await waitFor(() => expect(screen.getAllByTestId("warning-group")).toHaveLength(2));
    const [r, u] = screen.getAllByTestId("warning-group");
    expect(r!.dataset.currency).toBe("RUB");
    expect(r!.textContent).toMatch(/2 операции на 3\s000,00\s₽/);
    expect(u!.textContent).toMatch(/1 операция на 900,00\s\$/);
  });

  it("на узком экране сводка и её операции не выходят за край", async () => {
    withGroup();
    renderWithProviders(<WarningsSection />);
    await waitFor(() => expect(screen.getByTestId("warning-group")).toBeTruthy());
    expect(group().className).toContain("min-w-0");
    expect(group().parentElement!.className).toContain("grid-cols-1");
    expect(within(group()).getByRole("heading").querySelector("span")!.className).toContain("break-words");
    fireEvent.click(within(group()).getByRole("button", { name: /Показать операции/ }));
    expect(screen.getByTestId("warning-group-items").className).toContain("flex-col");
  });
});
