import type { ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";

/** Подтверждение/уведомление в стиле приложения вместо системных
 * confirm()/alert(). Без onConfirm — информационный диалог с кнопкой «Понятно».
 *
 * В опасном подтверждении (tone="danger") фокус стоит на «Отмена», чтобы
 * случайный Enter ничего не удалил. Ошибка запроса показывается внутри окна,
 * окно остаётся открытым — действие можно повторить. */
export function ConfirmModal({
  title,
  children,
  confirmLabel = "Удалить",
  tone = "danger",
  pending = false,
  error,
  onConfirm,
  onClose,
}: {
  title: string;
  children?: ReactNode;
  confirmLabel?: string;
  tone?: "danger" | "primary";
  pending?: boolean;
  error?: string | null | undefined;
  onConfirm?: () => void;
  onClose: () => void;
}) {
  return (
    <Modal title={title} onClose={onClose}>
      <div className="flex flex-col gap-6">
        {(children || error) && (
          <div className="text-[15px] text-ink-500">
            {children}
            {error && (
              <p role="alert" className="mt-3 text-sm text-danger">
                {error}
              </p>
            )}
          </div>
        )}
        <div className="flex justify-end gap-3">
          {onConfirm ? (
            <>
              <Button type="button" variant="secondary" onClick={onClose} autoFocus={tone === "danger"}>
                Отмена
              </Button>
              <Button
                type="button"
                variant={tone}
                disabled={pending}
                aria-busy={pending}
                onClick={() => {
                  if (!pending) onConfirm();
                }}
                autoFocus={tone !== "danger"}
              >
                {confirmLabel}
              </Button>
            </>
          ) : (
            <Button type="button" onClick={onClose} autoFocus>
              Понятно
            </Button>
          )}
        </div>
      </div>
    </Modal>
  );
}
