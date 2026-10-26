import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, RotateCw, Send, Sparkles, Square, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { Textarea } from "@/components/ui/Field";
import { assistantApi, chatErrorMessage, MAX_QUESTION_CHARS, type AssistantStatus } from "@/lib/api/assistant";
import { cn } from "@/lib/cn";

import { isGenerating, useChatStore, type ChatMessage } from "./chatStore";

const QUICK_QUESTIONS = [
  "Коротко опиши мою финансовую ситуацию",
  "Что с бюджетами в этом месяце?",
  "Какие у меня долги и сроки?",
  "Куда уходит больше всего денег?",
];

function StatusCard({ status, onRetry, retrying }: { status: AssistantStatus; onRetry: () => void; retrying: boolean }) {
  return (
    <Card className="border-warn/30 bg-warn-soft/40">
      <div className="flex flex-wrap items-start gap-4">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warn" strokeWidth={1.75} />
        <div className="min-w-0 flex-1">
          <p className="text-[15px] font-medium text-ink-900">Помощник пока недоступен</p>
          <p className="mt-1 text-[15px] text-ink-700">{status.message}</p>
          {status.state === "model_not_found" && (
            <code className="mt-2 inline-block rounded-md bg-surface px-2 py-1 text-sm text-ink-900">
              ollama pull {status.model.name}
            </code>
          )}
        </div>
        <Button variant="secondary" size="sm" onClick={onRetry} disabled={retrying}>
          <RotateCw className={cn("h-3.5 w-3.5", retrying && "animate-spin")} strokeWidth={1.75} />
          Проверить снова
        </Button>
      </div>
    </Card>
  );
}

function AnswerFooter({ message }: { message: ChatMessage }) {
  if (message.status === "stopped") {
    return <p className="mt-2 text-sm text-ink-400">Ответ остановлен.</p>;
  }
  if (message.status === "error") {
    return (
      <p role="alert" className="mt-2 text-sm text-danger">
        {message.error}
      </p>
    );
  }
  if (message.status !== "done" || !message.grounding) return null;
  const { checked, unverified } = message.grounding;
  return (
    <div className="mt-3 flex flex-col gap-1.5 text-sm">
      {unverified.length > 0 ? (
        <p data-testid="unverified" className="flex items-start gap-1.5 text-warn">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={1.75} />
          <span>
            Не удалось сверить с данными приложения: {unverified.join(", ")}. Проверьте эти значения на экранах
            приложения — помощник мог ошибиться.
          </span>
        </p>
      ) : checked > 0 ? (
        <p className="flex items-center gap-1.5 text-success">
          <CheckCircle2 className="h-4 w-4" strokeWidth={1.75} />
          Числа в ответе совпадают с данными приложения ({checked}).
        </p>
      ) : null}
      {message.truncated && <p className="text-ink-400">Ответ обрезан по длине.</p>}
    </div>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <li
      data-testid={isUser ? "user-message" : "assistant-message"}
      data-status={message.status}
      className={cn("flex", isUser ? "justify-end" : "justify-start")}
    >
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-4 py-3 text-[15px] leading-relaxed",
          isUser ? "bg-accent-soft text-ink-900" : "border border-border bg-surface text-ink-900",
        )}
      >
        {/* Текст выводится как текст: React экранирует его, HTML и ссылки не исполняются. */}
        {message.content && <p className="whitespace-pre-wrap break-words">{message.content}</p>}
        {!isUser && message.status === "streaming" && (
          <p className="flex items-center gap-2 text-sm text-ink-400" aria-live="polite">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-accent" />
            {message.content ? "Помощник отвечает…" : "Помощник читает данные и готовит ответ…"}
          </p>
        )}
        {!isUser && <AnswerFooter message={message} />}
      </div>
    </li>
  );
}

export function AssistantPage() {
  const status = useQuery({ queryKey: ["assistant-status"], queryFn: assistantApi.status, retry: false });
  const messages = useChatStore((s) => s.messages);
  const question = useChatStore((s) => s.draft);
  const setQuestion = useChatStore((s) => s.setDraft);
  const sendToStore = useChatStore((s) => s.send);
  const stop = useChatStore((s) => s.stop);
  const clear = useChatStore((s) => s.clear);
  const [confirmClear, setConfirmClear] = useState(false);
  const listEndRef = useRef<HTMLDivElement | null>(null);
  const generating = isGenerating(messages);

  useEffect(() => {
    listEndRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages]);

  // Уход со страницы генерацию не прерывает: ответ дописывается в хранилище
  // диалога и виден при возвращении (см. chatStore).

  const ready = status.data?.ready === true;
  const trimmed = question.trim();
  const tooLong = question.length > MAX_QUESTION_CHARS;
  const canSend = ready && !generating && trimmed.length > 0 && !tooLong;

  const send = (text: string) => {
    if (ready) void sendToStore(text);
  };

  const lastQuestion = [...messages].reverse().find((m) => m.role === "user")?.content;
  const lastFailed = messages.length > 0 && messages[messages.length - 1]!.status === "error";

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <h1 className="text-[28px] font-semibold tracking-tight text-ink-900">Помощник</h1>
          {status.data?.ready && <Badge tone="ok">{status.data.model.name}</Badge>}
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setConfirmClear(true)}
          disabled={generating || messages.length === 0}
        >
          <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />
          Очистить диалог
        </Button>
      </div>

      {status.isPending ? (
        <p className="text-[15px] text-ink-500">Проверяю локальную модель…</p>
      ) : status.isError ? (
        <Card>
          <p role="alert" className="text-[15px] text-danger">
            Не удалось проверить помощника: {chatErrorMessage(status.error)}
          </p>
        </Card>
      ) : (
        status.data && !status.data.ready && (
          <StatusCard status={status.data} onRetry={() => status.refetch()} retrying={status.isFetching} />
        )
      )}

      <Card>
        <CardHeader title="Диалог" />
        {messages.length === 0 ? (
          <div className="flex flex-col items-center gap-4 py-8 text-center">
            <Sparkles className="h-8 w-8 text-accent" strokeWidth={1.5} />
            <p className="max-w-md text-[15px] text-ink-500">
              Спросите о своих финансах: помощник объяснит ситуацию по данным приложения. Модель работает
              только на этом компьютере.
            </p>
            <div className="flex flex-wrap justify-center gap-2">
              {QUICK_QUESTIONS.map((q) => (
                <button
                  key={q}
                  type="button"
                  disabled={!ready}
                  onClick={() => send(q)}
                  className="rounded-full border border-border bg-surface px-3.5 py-1.5 text-sm text-ink-700 transition-colors hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <ul role="log" aria-live="polite" aria-busy={generating} className="flex flex-col gap-4">
            {messages.map((m) => (
              <MessageBubble key={m.id} message={m} />
            ))}
          </ul>
        )}
        <div ref={listEndRef} />

        {lastFailed && lastQuestion && !generating && (
          <div className="mt-3 flex justify-end">
            <Button variant="secondary" size="sm" onClick={() => send(lastQuestion)} disabled={!ready}>
              <RotateCw className="h-3.5 w-3.5" strokeWidth={1.75} />
              Повторить вопрос
            </Button>
          </div>
        )}

        <form
          className="mt-5 flex flex-col gap-2 border-t border-border pt-5"
          onSubmit={(e) => {
            e.preventDefault();
            if (canSend) send(question);
          }}
        >
          <Textarea
            aria-label="Вопрос помощнику"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (canSend) send(question);
              }
            }}
            rows={3}
            placeholder={ready ? "Например: хватит ли мне денег до конца месяца?" : "Помощник недоступен"}
            disabled={!ready}
          />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className={cn("text-sm", tooLong ? "text-danger" : "text-ink-400")}>
              {question.length} / {MAX_QUESTION_CHARS}
            </span>
            <div className="flex gap-2">
              {generating ? (
                <Button type="button" variant="danger" onClick={stop}>
                  <Square className="h-4 w-4" strokeWidth={1.75} />
                  Остановить
                </Button>
              ) : (
                <Button type="submit" disabled={!canSend}>
                  <Send className="h-4 w-4" strokeWidth={1.75} />
                  Отправить
                </Button>
              )}
            </div>
          </div>
        </form>
      </Card>

      <p className="text-sm text-ink-400">
        Помощник пересказывает данные приложения: все суммы посчитаны приложением, модель их не вычисляет. Он не
        выполняет операции и не является финансовым консультантом. Диалог хранится только в памяти приложения:
        он сохраняется при переходах между разделами и исчезает при обновлении страницы или закрытии приложения.
      </p>

      {confirmClear && (
        <ConfirmModal
          title="Очистить диалог?"
          confirmLabel="Очистить"
          onClose={() => setConfirmClear(false)}
          onConfirm={() => {
            clear();
            setConfirmClear(false);
          }}
        >
          Вся переписка с помощником будет удалена. Отменить это нельзя.
        </ConfirmModal>
      )}
    </div>
  );
}
