import { useEffect, useRef, useState } from "react";
import { RotateCcw } from "lucide-react";

import {
  CATEGORY_ICON_KEYS,
  CATEGORY_ICON_REGISTRY,
  CategoryIcon,
} from "@/lib/categoryIcons";
import { cn } from "@/lib/cn";

/** Кнопка с текущей иконкой категории и popover для выбора другой. value=null
 * — иконка подбирается автоматически по названию (см. lib/categoryIcons). */
export function CategoryIconPicker({
  value,
  onChange,
  name,
  type,
}: {
  value: string | null;
  onChange: (icon: string | null) => void;
  name: string;
  type: "income" | "expense";
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        // Закрываем только popover, а не всю модалку под ним.
        e.stopPropagation();
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="true"
        aria-expanded={open}
        aria-label="Выбрать иконку категории"
        title="Выбрать иконку"
        className={cn(
          "flex h-11 w-11 cursor-pointer items-center justify-center rounded-full border border-transparent bg-surface-hover text-ink-500 transition-colors",
          "hover:border-border-strong hover:text-ink-900",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
          open && "border-accent text-accent",
        )}
      >
        <CategoryIcon name={name} type={type} icon={value} className="h-[18px] w-[18px]" />
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Иконки категорий"
          className="absolute left-0 top-[calc(100%+8px)] z-10 w-[296px] rounded-xl border border-border bg-surface p-3 shadow-xl"
        >
          <div className="grid grid-cols-6 gap-1.5">
            {CATEGORY_ICON_KEYS.map((key) => {
              const Icon = CATEGORY_ICON_REGISTRY[key]!;
              const selected = value === key;
              return (
                <button
                  key={key}
                  type="button"
                  title={key}
                  aria-label={key}
                  aria-pressed={selected}
                  data-icon={key}
                  onClick={() => {
                    onChange(key);
                    setOpen(false);
                  }}
                  className={cn(
                    "flex h-10 w-10 cursor-pointer items-center justify-center rounded-lg text-ink-500 transition-colors",
                    "hover:bg-surface-hover hover:text-ink-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                    selected && "bg-accent-soft text-accent",
                  )}
                >
                  <Icon className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden />
                </button>
              );
            })}
          </div>
          <button
            type="button"
            onClick={() => {
              onChange(null);
              setOpen(false);
            }}
            className="mt-3 flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium text-ink-500 hover:bg-surface-hover hover:text-ink-900"
          >
            <RotateCcw className="h-3.5 w-3.5" strokeWidth={1.75} />
            Подобрать автоматически
          </button>
        </div>
      )}
    </div>
  );
}
