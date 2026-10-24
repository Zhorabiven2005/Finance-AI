/**
 * HTTP-клиент backend.
 *
 * Все запросы идут на относительный /api — в разработке Vite проксирует их
 * на http://127.0.0.1:8000. Ключей и секретов на фронтенде нет.
 */

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const BASE_URL = "/api/v1";

async function fetchApi(path: string, init?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      headers: { "Content-Type": "application/json", ...init?.headers },
      ...init,
    });
  } catch {
    throw new ApiError("Backend недоступен. Проверьте, что сервер запущен.", 0);
  }

  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = await response.text();
    }
    // FastAPI оборачивает ошибку в {"detail": ...} — распаковываем здесь,
    // один раз, а не в каждом месте, где отображается сообщение. Без этого
    // errorMessage() получал на вход весь объект {detail: "..."}, не строку,
    // и молча откатывался к générique "код 400" — реальная причина ошибки
    // (например, «у счёта есть операции») терялась.
    const detail =
      body && typeof body === "object" && "detail" in body
        ? (body as { detail: unknown }).detail
        : body;
    throw new ApiError(`Запрос ${path} завершился с кодом ${response.status}`, response.status, detail);
  }

  return response;
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetchApi(path, init);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Как apiRequest, но также отдаёт X-Total-Count — заголовок с общим числом
 * строк, подходящих под фильтр, без учёта limit/offset (пагинация
 * операций, Stage 2A). Тело ответа при этом остаётся обычным массивом. */
export async function apiRequestWithTotal<T>(
  path: string,
  init?: RequestInit,
): Promise<{ data: T; total: number }> {
  const response = await fetchApi(path, init);
  const total = Number(response.headers.get("X-Total-Count") ?? "0");
  const data = (await response.json()) as T;
  return { data, total };
}

/** Ошибка проверки формы на клиенте («Некорректная сумма»): её текст
 * написан для пользователя и показывается как есть. Обычный Error сюда не
 * относится — технические сообщения пользователю не показываются. */
export class FormError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FormError";
  }
}

/** Достаёт читаемое сообщение из ошибки API: detail — строка (наши
 * HTTPException) или список ошибок валидации Pydantic. */
export function errorMessage(err: unknown, fallback = "Не удалось выполнить запрос"): string {
  if (err instanceof FormError) return err.message;
  if (err instanceof ApiError) {
    const detail = err.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const messages = detail
        .map((d) => (d && typeof d === "object" && "msg" in d ? String(d.msg) : null))
        .filter((m): m is string => Boolean(m));
      if (messages.length) return messages.join("; ");
    }
    return err.message;
  }
  return fallback;
}

export const api = {
  get: <T>(path: string) => apiRequest<T>(path),
  post: <T>(path: string, body: unknown) =>
    apiRequest<T>(path, { method: "POST", body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) =>
    apiRequest<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  delete: <T>(path: string) => apiRequest<T>(path, { method: "DELETE" }),
};
