import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Insight, InsightsResponse } from "@/lib/api/insights";
import { renderWithProviders, rub } from "@/test/render";

import { InsightsSection, VISIBLE_INSIGHTS } from "./InsightsSection";

const enc = new TextEncoder();

function insight(over: Partial<Insight> = {}): Insight {
  return {
    id: "cash_flow:RUB",
    type: "cash_flow",
    title: "Доходы и расходы",
    severity: "attention",
    confidence: "medium",
    period: { key: "current_month", date_from: "2026-10-01", date_to: "2026-10-31", label: "октябрь 2026 (месяц ещё идёт)", complete: false },
    currency: "RUB",
    metrics: [
      { label: "Доходы", money: rub(10_000_000) },
      { label: "Расходы", money: rub(12_000_000) },
      { label: "Доля", percent: 55.2 },
      { label: "Операций", count: 7 },
    ],
    items: [{ label: "Переводы между своими счетами", money: rub(5_000_000), note: "1 шт.; не входят ни в доходы, ни в расходы" }],
    summary: "Расходы превысили доходы на 20 000,00 ₽.",
    limitations: ["Месяц ещё идёт: итоги изменятся."],
    link: { to: "/analytics", label: "Аналитика" },
    ...over,
  };
}

function response(over: Partial<InsightsResponse> = {}): InsightsResponse {
  return {
    generated_at: "2026-10-25T00:00:00Z",
    today: "2026-10-25",
    period: insight().period,
    currencies: ["RUB"],
    insights: [insight()],
    unavailable: [],
    ...over,
  };
}

let insightsPayload: InsightsResponse | null;
let insightsUrls: string[];
let explainBodies: unknown[];
let explainSignals: AbortSignal[];
let ready: boolean;
let stream: { send: (e: object) => void; close: () => void } | null;

beforeEach(() => {
  insightsPayload = response();
  insightsUrls = [];
  explainBodies = [];
  explainSignals = [];
  ready = true;
  stream = null;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.startsWith("/api/v1/insights?")) {
        insightsUrls.push(url);
        if (!insightsPayload) return new Response(JSON.stringify({ detail: "Ошибка расчёта" }), { status: 500 });
        return new Response(JSON.stringify(insightsPayload), { status: 200 });
      }
      if (url === "/api/v1/assistant/status") {
        return new Response(JSON.stringify({ ready, state: ready ? "ready" : "server_unreachable", message: "", model: { name: "m" } }), { status: 200 });
      }
      if (url === "/api/v1/insights/explain") {
        explainBodies.push(JSON.parse(init!.body as string));
        explainSignals.push(init!.signal!);
        let controller!: ReadableStreamDefaultController<Uint8Array>;
        const body = new ReadableStream<Uint8Array>({ start: (c) => void (controller = c) });
        init!.signal!.addEventListener("abort", () => controller.error(new DOMException("Aborted", "AbortError")));
        stream = {
          send: (e) => controller.enqueue(enc.encode(JSON.stringify(e) + "\n")),
          close: () => controller.close(),
        };
        return new Response(body, { status: 200 });
      }
      throw new Error(`unexpected fetch ${url}`);
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const cards = () => screen.queryAllByTestId("insight");

describe("Финансовые инсайты", () => {
  it("показывает тип, показатели, период, валюту, уверенность, ограничения и ссылку", async () => {
    renderWithProviders(<InsightsSection />);
    const card = (await screen.findAllByTestId("insight"))[0]!;
    const c = within(card);
    expect(c.getByText("Доходы и расходы", { selector: "h3" })).toBeTruthy();
    expect(c.getByText("Обратите внимание")).toBeTruthy();
    expect(c.getByText("октябрь 2026 (месяц ещё идёт) · RUB")).toBeTruthy();
    expect(card.textContent).toMatch(/100\s000,00\s₽/);
    expect(card.textContent).toContain("55,2%");
    expect(card.textContent).toContain("Операций7");
    expect(c.getByText("Уверенность: средняя")).toBeTruthy();
    expect(c.getByText("Месяц ещё идёт: итоги изменятся.")).toBeTruthy();
    expect(c.getByText("Расходы превысили доходы на 20 000,00 ₽.")).toBeTruthy();
    expect(c.getByRole("link", { name: /Аналитика/ }).getAttribute("href")).toBe("/analytics");
  });

  it("не перегружает экран: сначала несколько выводов, остальные по кнопке", async () => {
    insightsPayload = response({ insights: Array.from({ length: 6 }, (_, i) => insight({ id: `x:${i}`, title: `Вывод ${i}` })) });
    renderWithProviders(<InsightsSection />);
    await waitFor(() => expect(cards()).toHaveLength(VISIBLE_INSIGHTS));
    fireEvent.click(screen.getByRole("button", { name: "Показать все (6)" }));
    expect(cards()).toHaveLength(6);
    fireEvent.click(screen.getByRole("button", { name: "Свернуть" }));
    expect(cards()).toHaveLength(VISIBLE_INSIGHTS);
  });

  it("пустые данные: понятное сообщение и причины, почему выводов нет", async () => {
    insightsPayload = response({
      insights: [],
      unavailable: [{ type: "recurring_expenses", currency: null, kind: "insufficient_data", reason: "Нужна история хотя бы за 2 месяца." }],
    });
    renderWithProviders(<InsightsSection />);
    expect(await screen.findByText("Пока недостаточно данных для выводов за этот период.")).toBeTruthy();
    expect(screen.getByText("Почему нет других выводов (1)")).toBeTruthy();
    expect(screen.getByText(/Регулярные платежи: Нужна история хотя бы за 2 месяца/)).toBeTruthy();
  });

  it("ошибка загрузки — сообщение и повтор", async () => {
    insightsPayload = null;
    renderWithProviders(<InsightsSection />);
    expect(await screen.findByText(/Не удалось посчитать инсайты/)).toBeTruthy();
    insightsPayload = response();
    fireEvent.click(screen.getByRole("button", { name: /Повторить|Обновить|Попробовать/ }));
    await waitFor(() => expect(cards()).toHaveLength(1));
  });

  it("переключение периода запрашивает выводы за другой период", async () => {
    renderWithProviders(<InsightsSection />);
    await screen.findAllByTestId("insight");
    fireEvent.click(screen.getByRole("tab", { name: "Прошлый месяц" }));
    await waitFor(() => expect(insightsUrls.at(-1)).toBe("/api/v1/insights?period=previous_month"));
    expect(screen.getByRole("tab", { name: "Прошлый месяц" }).getAttribute("aria-selected")).toBe("true");
  });

  it("недоверенные названия — только текст", async () => {
    insightsPayload = response({ insights: [insight({ items: [{ label: '<img src=x onerror="alert(1)">', money: rub(100) }] })] });
    const { container } = renderWithProviders(<InsightsSection />);
    await screen.findAllByTestId("insight");
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText('<img src=x onerror="alert(1)">')).toBeTruthy();
  });
});

describe("Финансовые инсайты: объяснение локальной моделью", () => {
  it("модель недоступна — числовые выводы видны, кнопки объяснения нет", async () => {
    ready = false;
    renderWithProviders(<InsightsSection />);
    await screen.findAllByTestId("insight");
    await waitFor(() => expect(screen.getByText(/Объяснения локальной модели сейчас недоступны/)).toBeTruthy());
    expect(screen.queryByRole("button", { name: /Объяснить/ })).toBeNull();
    expect(screen.getByText("Расходы превысили доходы на 20 000,00 ₽.")).toBeTruthy();
  });

  it("объяснение идёт потоком; в запросе только id и период", async () => {
    renderWithProviders(<InsightsSection />);
    fireEvent.click(await screen.findByRole("button", { name: /Объяснить/ }));
    await waitFor(() => expect(stream).not.toBeNull());
    expect(explainBodies[0]).toEqual({ insight_id: "cash_flow:RUB", period: "current_month" });
    await act(async () => {
      stream!.send({ type: "meta", model: "m" });
      stream!.send({ type: "delta", text: "Расходы выше доходов на 20 000 ₽." });
    });
    const block = await screen.findByTestId("insight-explanation");
    expect(block.textContent).toContain("Модель пишет");
    await act(async () => {
      stream!.send({ type: "done", finish_reason: "stop", truncated: false, grounding: { checked: 1, unverified: [] }, usage: {} });
      stream!.close();
    });
    await waitFor(() => expect(block.textContent).toContain("Числа совпадают с расчётом приложения (1)"));
    expect(block.textContent).toContain("Расходы выше доходов на 20 000 ₽.");
  });

  it("непроверенные числа помечены", async () => {
    renderWithProviders(<InsightsSection />);
    fireEvent.click(await screen.findByRole("button", { name: /Объяснить/ }));
    await waitFor(() => expect(stream).not.toBeNull());
    await act(async () => {
      stream!.send({ type: "delta", text: "Вы потратили 99 999 ₽." });
      stream!.send({ type: "done", finish_reason: "stop", truncated: false, grounding: { checked: 1, unverified: ["99 999"] }, usage: {} });
      stream!.close();
    });
    expect((await screen.findByTestId("explanation-unverified")).textContent).toContain("99 999");
  });

  it("ошибка модели — сообщение и «Повторить», карточка остаётся", async () => {
    renderWithProviders(<InsightsSection />);
    fireEvent.click(await screen.findByRole("button", { name: /Объяснить/ }));
    await waitFor(() => expect(stream).not.toBeNull());
    await act(async () => {
      stream!.send({ type: "error", code: "server_unreachable", message: "Ollama не запущен." });
      stream!.close();
    });
    expect((await screen.findByRole("alert")).textContent).toContain("Ollama не запущен.");
    expect(screen.getByRole("button", { name: "Повторить" })).toBeTruthy();
    expect(screen.getByText("Расходы превысили доходы на 20 000,00 ₽.")).toBeTruthy();
  });

  it("обрыв без done — не «готово», а ошибка; «Остановить» отменяет запрос", async () => {
    const view = renderWithProviders(<InsightsSection />);
    fireEvent.click(await screen.findByRole("button", { name: /Объяснить/ }));
    await waitFor(() => expect(stream).not.toBeNull());
    await act(async () => {
      stream!.send({ type: "delta", text: "Половина" });
      stream!.close();
    });
    expect((await screen.findByRole("alert")).textContent).toContain("оборвалось");

    stream = null;
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    await waitFor(() => expect(stream).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: /Остановить/ }));
    await waitFor(() => expect(screen.getByText("Объяснение остановлено.")).toBeTruthy());
    expect(explainSignals[1]!.aborted).toBe(true);
    view.unmount();
  });

  it("уход со страницы отменяет объяснение", async () => {
    const view = renderWithProviders(<InsightsSection />);
    fireEvent.click(await screen.findByRole("button", { name: /Объяснить/ }));
    await waitFor(() => expect(stream).not.toBeNull());
    view.unmount();
    expect(explainSignals[0]!.aborted).toBe(true);
  });
});
