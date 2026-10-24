import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

type Tone = "neutral" | "ok" | "warn" | "danger";

const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-surface-hover text-ink-500",
  ok: "bg-success-soft text-success",
  warn: "bg-warn-soft text-warn",
  danger: "bg-danger-soft text-danger",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium",
        TONE_CLASSES[tone],
      )}
    >
      {children}
    </span>
  );
}
