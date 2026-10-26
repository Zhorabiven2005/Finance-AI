import { api, ApiError, errorMessage } from "@/lib/api/client";

/** Локальный AI-помощник (Stage 3B). Ответ приходит потоком NDJSON
 * (по JSON-событию на строку) с POST /api/v1/assistant/chat. */

export type AssistantState =
  | "ready"
  | "disabled"
  | "server_unreachable"
  | "server_timeout"
  | "server_bad_response"
  | "model_not_found"
  | "model_not_local";

export interface AssistantStatus {
  enabled: boolean;
  provider: "ollama";
  state: AssistantState;
  ready: boolean;
  message: string;
  server: { url: string; available: boolean; version: string | null };
  model: {
    name: string;
    available: boolean;
    local: boolean | null;
    size_bytes: number | null;
    parameter_size: string | null;
    quantization: string | null;
  };
  checked_at: string;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface Grounding {
  checked: number;
  unverified: string[];
}

export type StreamEvent =
  | {
      type: "meta";
      model: string;
      context_generated_at: string;
      digest_tokens: number;
      omitted_sections: string[];
      /** Расчёт плана по цели (backend), если вопрос о цели; UI его не показывает. */
      goal_calculation?: Record<string, unknown> | null;
    }
  | { type: "delta"; text: string }
  | {
      type: "done";
      finish_reason: "stop" | "length" | "output_limit";
      truncated: boolean;
      grounding: Grounding;
      usage: { prompt_tokens: number | null; output_tokens: number | null };
    }
  | { type: "error"; code: string; message: string };

const KNOWN_EVENTS = new Set(["meta", "delta", "done", "error"]);

/** Длина вопроса — тот же лимит, что у backend по умолчанию
 * (ASSISTANT_MAX_QUESTION_CHARS). Backend всё равно проверяет сам. */
export const MAX_QUESTION_CHARS = 1000;

/** Разбор NDJSON по кускам: кусок может оборваться посреди строки и даже
 * посреди символа UTF-8. Неизвестные типы событий (например, рассуждения
 * модели, если они когда-нибудь появятся в потоке) отбрасываются — в UI
 * попадают только meta / delta / done / error. */
export function createNdjsonParser(onEvent: (event: StreamEvent) => void) {
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  const handleLine = (line: string) => {
    if (!line.trim()) return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(line);
    } catch {
      throw new Error("Некорректный ответ сервера");
    }
    if (parsed && typeof parsed === "object" && KNOWN_EVENTS.has((parsed as { type?: string }).type ?? "")) {
      onEvent(parsed as StreamEvent);
    }
  };

  return {
    push(chunk: Uint8Array) {
      buffer += decoder.decode(chunk, { stream: true });
      let newline = buffer.indexOf("\n");
      while (newline !== -1) {
        handleLine(buffer.slice(0, newline));
        buffer = buffer.slice(newline + 1);
        newline = buffer.indexOf("\n");
      }
    },
    finish() {
      buffer += decoder.decode();
      handleLine(buffer);
      buffer = "";
    },
  };
}

/** Отправляет диалог и читает поток событий. Отмена — через signal
 * (AbortController): fetch бросает AbortError, соединение закрывается, backend
 * прекращает генерацию. История нигде не сохраняется — только в памяти приложения (chatStore). */
export async function streamChat(
  messages: ChatTurn[],
  options: { signal: AbortSignal; onEvent: (event: StreamEvent) => void },
): Promise<void> {
  return postNdjson("/api/v1/assistant/chat", { messages }, options);
}

/** POST с потоковым ответом NDJSON локальной модели — общий для чата и
 * объяснения инсайтов (Stage 3C): те же события, отмена и ошибки. */
export async function postNdjson(
  url: string,
  body: unknown,
  { signal, onEvent }: { signal: AbortSignal; onEvent: (event: StreamEvent) => void },
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (signal.aborted) throw err;
    throw new ApiError("Backend недоступен. Проверьте, что сервер запущен.", 0);
  }
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = ((await response.json()) as { detail?: unknown }).detail;
    } catch {
      detail = undefined;
    }
    throw new ApiError(`Запрос к помощнику завершился с кодом ${response.status}`, response.status, detail);
  }
  if (!response.body) throw new Error("Ответ без потока данных");

  const reader = response.body.getReader();
  const parser = createNdjsonParser(onEvent);
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) parser.push(value);
    }
    parser.finish();
  } finally {
    reader.releaseLock();
  }
}

export function chatErrorMessage(err: unknown): string {
  return errorMessage(err, "Не удалось получить ответ помощника");
}

export const assistantApi = {
  status: () => api.get<AssistantStatus>("/assistant/status"),
};
