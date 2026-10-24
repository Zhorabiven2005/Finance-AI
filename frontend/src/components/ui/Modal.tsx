import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

// md без прокрутки: в маленьких формах есть всплывающие элементы (выбор
// иконки категории), которые выходят за край окна и не должны обрезаться.
const SIZE_CLASS = {
  md: "max-w-md",
  lg: "max-w-2xl max-h-[90vh] overflow-y-auto",
  xl: "max-w-5xl max-h-[90vh] overflow-y-auto",
} as const;

export function Modal({
  title,
  onClose,
  children,
  size = "md",
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  size?: "md" | "lg" | "xl";
}) {
  // Элемент, открывший окно, запоминается во время первого рендера — до того,
  // как autoFocus внутри окна заберёт фокус. После закрытия фокус
  // возвращается к нему (если он ещё на странице: строку могли удалить).
  const [opener] = useState(() =>
    typeof document !== "undefined" && document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null,
  );
  const dialogRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    return () => {
      // StrictMode в разработке «перезапускает» эффекты, не убирая окно: тогда
      // оно ещё в документе, и фокус трогать нельзя — иначе он уйдёт с
      // кнопки «Отмена» обратно на страницу.
      if (dialog?.isConnected) return;
      if (opener && opener !== document.body && opener.isConnected) opener.focus();
    };
  }, [opener]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-ink-900/40 backdrop-blur-[2px]"
        onClick={onClose}
        aria-hidden
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`relative w-full rounded-2xl border border-border bg-surface p-7 shadow-xl ${SIZE_CLASS[size]}`}
      >
        <div className="mb-6 flex items-center justify-between">
          <h2 className="text-xl font-semibold text-ink-900">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-ink-400 hover:bg-surface-hover hover:text-ink-900"
            aria-label="Закрыть"
          >
            <X className="h-5 w-5" strokeWidth={1.75} />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
