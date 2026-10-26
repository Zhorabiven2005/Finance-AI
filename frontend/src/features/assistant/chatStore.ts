import { create } from "zustand";

import { chatErrorMessage, MAX_QUESTION_CHARS, streamChat, type ChatTurn, type Grounding } from "@/lib/api/assistant";

/** Диалог с помощником живёт здесь, а не в состоянии страницы: страница
 * размонтируется при переходе в другой раздел, а хранилище — нет. Поэтому
 * переписка переживает навигацию, а начатая генерация продолжается в фоне и
 * дописывает ответ в то же сообщение.
 *
 * Только память JS: ни localStorage, ни backend — при обновлении или закрытии
 * приложения диалог исчезает. */

export type MessageStatus = "streaming" | "done" | "stopped" | "error";

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  status: MessageStatus;
  error?: string;
  grounding?: Grounding;
  truncated?: boolean;
}

/** Сколько последних реплик отправлять вместе с вопросом (backend всё равно
 * ограничивает историю сам). */
export const HISTORY_LIMIT = 8;

interface ChatState {
  messages: ChatMessage[];
  /** Недописанный вопрос — тоже не теряется при переходах. */
  draft: string;
  setDraft: (draft: string) => void;
  send: (text: string) => Promise<void>;
  stop: () => void;
  clear: () => void;
}

let nextId = 1;
/** Запрос, который сейчас идёт. Вне состояния: это не данные для UI, а
 * ручка отмены. Пока он не null, второй запрос не отправляется. */
let activeController: AbortController | null = null;

export const isGenerating = (messages: ChatMessage[]) => messages.some((m) => m.status === "streaming");

export const useChatStore = create<ChatState>((set, get) => {
  const update = (id: number, patch: (m: ChatMessage) => Partial<ChatMessage>) =>
    set((state) => ({ messages: state.messages.map((m) => (m.id === id ? { ...m, ...patch(m) } : m)) }));

  return {
    messages: [],
    draft: "",
    setDraft: (draft) => set({ draft }),

    async send(text) {
      const content = text.trim();
      const { messages } = get();
      if (!content || content.length > MAX_QUESTION_CHARS || activeController || isGenerating(messages)) return;
      // В историю для модели идут только завершённые реплики.
      const history: ChatTurn[] = messages
        .filter((m) => m.content && (m.role === "user" || m.status === "done"))
        .slice(-HISTORY_LIMIT)
        .map((m) => ({ role: m.role, content: m.content }));
      const controller = new AbortController();
      activeController = controller;
      const answerId = nextId + 1;
      set((state) => ({
        draft: "",
        messages: [
          ...state.messages,
          { id: nextId, role: "user", content, status: "done" },
          { id: answerId, role: "assistant", content: "", status: "streaming" },
        ],
      }));
      nextId += 2;

      // «Готово» ставится только по событию done от backend: обрыв потока
      // без него — ошибка, а не завершённый ответ.
      let finished = false;
      try {
        await streamChat([...history, { role: "user", content }], {
          signal: controller.signal,
          onEvent: (event) => {
            if (event.type === "delta") {
              update(answerId, (m) => ({ content: m.content + event.text }));
            } else if (event.type === "done") {
              finished = true;
              update(answerId, () => ({ status: "done", grounding: event.grounding, truncated: event.truncated }));
            } else if (event.type === "error") {
              finished = true;
              update(answerId, () => ({ status: "error", error: event.message }));
            }
          },
        });
        if (!finished) {
          update(answerId, () => ({ status: "error", error: "Ответ оборвался. Попробуйте снова." }));
        }
      } catch (err) {
        if (controller.signal.aborted) {
          update(answerId, () => ({ status: "stopped" }));
        } else {
          update(answerId, () => ({ status: "error", error: chatErrorMessage(err) }));
        }
      } finally {
        if (activeController === controller) activeController = null;
      }
    },

    stop: () => activeController?.abort(),

    clear() {
      // Очистка во время генерации сначала отменяет запрос, чтобы поздний
      // ответ не появился в новом пустом диалоге.
      activeController?.abort();
      activeController = null;
      set({ messages: [], draft: "" });
    },
  };
});

/** Для тестов: чистое состояние между сценариями. */
export function resetChatStore() {
  useChatStore.getState().clear();
}
