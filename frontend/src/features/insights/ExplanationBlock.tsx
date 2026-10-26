import { AlertTriangle, CheckCircle2, Sparkles, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { chatErrorMessage, type Grounding } from "@/lib/api/assistant";
import { streamInsightExplanation, type InsightPeriodKey } from "@/lib/api/insights";

type Explanation =
  | { status: "idle" }
  | { status: "streaming"; text: string }
  | { status: "done"; text: string; grounding: Grounding; truncated: boolean }
  | { status: "stopped"; text: string }
  | { status: "error"; text: string; error: string };

/** Объяснение одного вывода локальной моделью: от клиента уходят только id и
 * период, текст для модели собирает backend из посчитанных значений. */
export function ExplanationBlock({ insightId, period }: { insightId: string; period: InsightPeriodKey }) {
  const [state, setState] = useState<Explanation>({ status: "idle" });
  const controllerRef = useRef<AbortController | null>(null);

  // Объяснение привязано к карточке: при уходе со страницы запрос отменяется
  // и не дописывается в никуда.
  useEffect(() => () => controllerRef.current?.abort(), []);

  async function run() {
    if (controllerRef.current) return;
    const controller = new AbortController();
    controllerRef.current = controller;
    let text = "";
    let finished = false;
    setState({ status: "streaming", text });
    try {
      await streamInsightExplanation(insightId, period, {
        signal: controller.signal,
        onEvent: (event) => {
          if (event.type === "delta") {
            text += event.text;
            setState({ status: "streaming", text });
          } else if (event.type === "done") {
            finished = true;
            setState({ status: "done", text, grounding: event.grounding, truncated: event.truncated });
          } else if (event.type === "error") {
            finished = true;
            setState({ status: "error", text, error: event.message });
          }
        },
      });
      if (!finished) setState({ status: "error", text, error: "Объяснение оборвалось. Попробуйте снова." });
    } catch (err) {
      if (controller.signal.aborted) setState({ status: "stopped", text });
      else setState({ status: "error", text, error: chatErrorMessage(err) });
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  }

  if (state.status === "idle") {
    return (
      <Button variant="secondary" size="sm" onClick={() => void run()}>
        <Sparkles className="h-3.5 w-3.5" strokeWidth={1.75} />
        Объяснить
      </Button>
    );
  }
  return (
    <div data-testid="insight-explanation" className="rounded-xl bg-accent-soft/50 px-4 py-3 text-[15px] text-ink-900">
      <p className="mb-1 text-xs font-medium text-ink-500">Объяснение локальной модели по числам выше</p>
      {state.text && <p className="whitespace-pre-wrap break-words leading-relaxed">{state.text}</p>}
      {state.status === "streaming" && (
        <div className="mt-2 flex items-center justify-between gap-3">
          <span className="flex items-center gap-2 text-sm text-ink-400" aria-live="polite">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-accent" />
            {state.text ? "Модель пишет…" : "Модель читает вывод…"}
          </span>
          <Button variant="secondary" size="sm" onClick={() => controllerRef.current?.abort()}>
            <Square className="h-3.5 w-3.5" strokeWidth={1.75} />
            Остановить
          </Button>
        </div>
      )}
      {state.status === "stopped" && <p className="mt-2 text-sm text-ink-400">Объяснение остановлено.</p>}
      {state.status === "error" && (
        <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
          <p role="alert" className="text-sm text-danger">
            {state.error}
          </p>
          <Button variant="secondary" size="sm" onClick={() => void run()}>
            Повторить
          </Button>
        </div>
      )}
      {state.status === "done" &&
        (state.grounding.unverified.length > 0 ? (
          <p data-testid="explanation-unverified" className="mt-2 flex items-start gap-1.5 text-sm text-warn">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={1.75} />
            <span>
              Не удалось сверить с расчётом: {state.grounding.unverified.join(", ")}. Опирайтесь на числа карточки.
            </span>
          </p>
        ) : state.grounding.checked > 0 ? (
          <p className="mt-2 flex items-center gap-1.5 text-sm text-success">
            <CheckCircle2 className="h-4 w-4" strokeWidth={1.75} />
            Числа совпадают с расчётом приложения ({state.grounding.checked}).
          </p>
        ) : null)}
    </div>
  );
}
