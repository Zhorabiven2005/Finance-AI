import { useQuery } from "@tanstack/react-query";

import { systemApi } from "@/lib/api/system";
import { formatMinor } from "@/lib/money";
import { cn } from "@/lib/cn";

function Row({ label, value, tone = "normal" }: {
  label: string;
  value: string;
  tone?: "normal" | "ok" | "warn";
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-ink-800 py-3 last:border-0">
      <span className="text-sm text-ink-400">{label}</span>
      <span
        className={cn(
          "tabular text-sm",
          tone === "ok" && "text-accent",
          tone === "warn" && "text-warn",
        )}
      >
        {value}
      </span>
    </div>
  );
}

export function SystemStatus() {
  const health = useQuery({ queryKey: ["health"], queryFn: systemApi.health });
  const settings = useQuery({ queryKey: ["settings"], queryFn: systemApi.settings });

  if (health.isPending) {
    return <p className="text-sm text-ink-400">Проверяю подключение к backend…</p>;
  }

  if (health.isError) {
    return (
      <div className="rounded-lg border border-danger/40 bg-danger/5 p-5">
        <p className="text-sm font-medium text-danger">Backend не отвечает</p>
        <p className="mt-2 text-sm text-ink-200">
          Запустите start.bat или выполните в каталоге backend:
        </p>
        <code className="mt-2 block rounded bg-ink-900 px-3 py-2 text-xs text-ink-200">
          uvicorn app.main:app --reload
        </code>
      </div>
    );
  }

  const currency = settings.data?.currency;

  return (
    <section className="rounded-lg border border-ink-800 bg-ink-900/60 px-5 py-1">
      <Row label="Backend" value={`${health.data.app} ${health.data.version}`} />
      <Row
        label="База данных"
        value={health.data.database}
        tone={health.data.database === "ok" ? "ok" : "warn"}
      />
      <Row label="Базовая валюта" value={settings.data?.base_currency ?? "—"} />
      <Row
        label="AI-провайдер"
        value={health.data.ai_configured ? "подключён" : "не настроен (этап 6)"}
        tone={health.data.ai_configured ? "ok" : "normal"}
      />
      <Row
        label="Проверка формата сумм"
        value={currency ? formatMinor(123456, currency) : "—"}
      />
    </section>
  );
}
