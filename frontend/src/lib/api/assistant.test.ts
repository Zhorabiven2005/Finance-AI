import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";

import { createNdjsonParser, streamChat, type StreamEvent } from "./assistant";

const enc = new TextEncoder();

function collect(chunks: Uint8Array[]): StreamEvent[] {
  const events: StreamEvent[] = [];
  const parser = createNdjsonParser((e) => events.push(e));
  for (const c of chunks) parser.push(c);
  parser.finish();
  return events;
}

function bytesSplit(text: string, size: number): Uint8Array[] {
  const all = enc.encode(text);
  const out: Uint8Array[] = [];
  for (let i = 0; i < all.length; i += size) out.push(all.slice(i, i + size));
  return out;
}

const STREAM = [
  { type: "meta", model: "m", context_generated_at: "2026-10-17T00:00:00Z", digest_tokens: 10, omitted_sections: [] },
  { type: "delta", text: "Расходы — 36 000,00 ₽" },
  { type: "delta", text: ", всё ок." },
  { type: "done", finish_reason: "stop", truncated: false, grounding: { checked: 1, unverified: [] }, usage: { prompt_tokens: 1, output_tokens: 2 } },
]
  .map((e) => JSON.stringify(e))
  .join("\n");

describe("Разбор потока NDJSON", () => {
  it.each([1, 3, 7, 64])("куски по %i байт: посреди строк и символов UTF-8", (size) => {
    const events = collect(bytesSplit(STREAM + "\n", size));
    expect(events.map((e) => e.type)).toEqual(["meta", "delta", "delta", "done"]);
    expect(events.filter((e) => e.type === "delta").map((e) => (e as { text: string }).text).join("")).toBe(
      "Расходы — 36 000,00 ₽, всё ок.",
    );
  });

  it("последняя строка без перевода строки тоже разбирается", () => {
    expect(collect([enc.encode(STREAM)]).at(-1)?.type).toBe("done");
  });

  it("неизвестные типы событий (например, рассуждения) отбрасываются", () => {
    const text = [
      JSON.stringify({ type: "thinking", text: "секретные рассуждения" }),
      JSON.stringify({ type: "delta", text: "Ответ" }),
      JSON.stringify({ text: "без типа" }),
    ].join("\n");
    expect(collect([enc.encode(text)])).toEqual([{ type: "delta", text: "Ответ" }]);
  });

  it("мусор вместо JSON — ошибка", () => {
    expect(() => collect([enc.encode("<html>\n")])).toThrow("Некорректный ответ сервера");
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("streamChat", () => {
  it("отправляет диалог и отдаёт события", async () => {
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        for (const chunk of bytesSplit(STREAM, 5)) c.enqueue(chunk);
        c.close();
      },
    });
    const fetchMock = vi.fn(async () => new Response(body, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const events: StreamEvent[] = [];
    await streamChat([{ role: "user", content: "Вопрос" }], { signal: new AbortController().signal, onEvent: (e) => events.push(e) });
    expect(events.map((e) => e.type)).toEqual(["meta", "delta", "delta", "done"]);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/assistant/chat");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ messages: [{ role: "user", content: "Вопрос" }] });
  });

  it("ошибка проверки запроса — ApiError с текстом backend", async () => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ detail: "Вопрос длиннее 1000 символов" }), { status: 422 }));
    const err = await streamChat([{ role: "user", content: "x" }], { signal: new AbortController().signal, onEvent: () => {} }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).detail).toBe("Вопрос длиннее 1000 символов");
  });

  it("backend недоступен — понятная ошибка", async () => {
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("Failed to fetch");
    });
    const err = await streamChat([{ role: "user", content: "x" }], { signal: new AbortController().signal, onEvent: () => {} }).catch((e) => e);
    expect((err as ApiError).message).toContain("Backend недоступен");
  });
});
