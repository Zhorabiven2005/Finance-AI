import { useMutation } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { errorMessage } from "@/lib/api/client";
import { dataTransferApi, type BackupPreview, type BackupSection } from "@/lib/api/dataTransfer";

const SECTION_LABELS: [BackupSection, string][] = [
  ["accounts", "Счета"],
  ["categories", "Категории"],
  ["transactions", "Операции"],
  ["transfers", "Переводы"],
  ["debts", "Долги"],
  ["debt_payments", "Платежи по долгам"],
  ["budgets", "Бюджеты"],
  ["recurring_transactions", "Регулярные операции"],
  ["goals", "Цели"],
  ["goal_entries", "Записи целей"],
  ["notifications", "Уведомления"],
];

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function BackupRestoreModal({
  file,
  preview,
  onClose,
  onRestored,
}: {
  file: File;
  preview: BackupPreview;
  onClose: () => void;
  onRestored: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const restore = useMutation({
    mutationFn: () => dataTransferApi.restoreBackup(file),
    onSuccess: onRestored,
    onError: (err) => setError(errorMessage(err, "Не удалось восстановить данные")),
  });

  if (!preview.valid) {
    return (
      <Modal title="Резервная копия не прошла проверку" onClose={onClose} size="lg">
        <div className="flex flex-col gap-5">
          <p className="text-[15px] text-ink-500">
            Файл «{file.name}» не будет импортирован. Текущие данные не изменены.
          </p>
          <ul className="flex flex-col gap-2 rounded-xl border border-danger/25 bg-danger-soft p-4 text-sm text-danger">
            {preview.errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
          {preview.errors_total > preview.errors.length && (
            <p className="text-sm text-ink-500">
              И ещё ошибок: {preview.errors_total - preview.errors.length}.
            </p>
          )}
          <div className="flex justify-end">
            <Button type="button" onClick={onClose}>
              Закрыть
            </Button>
          </div>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title="Восстановление из резервной копии" onClose={onClose} size="lg">
      <div className="flex flex-col gap-5">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-[15px]">
          <dt className="text-ink-500">Файл</dt>
          <dd className="truncate text-ink-900">{file.name}</dd>
          <dt className="text-ink-500">Дата резервной копии</dt>
          <dd className="text-ink-900">{formatDateTime(preview.exported_at)}</dd>
          <dt className="text-ink-500">Базовая валюта</dt>
          <dd className="text-ink-900">{preview.base_currency}</dd>
        </dl>

        <ul className="grid grid-cols-2 gap-x-6 gap-y-2 rounded-xl border border-border bg-page/60 p-4 text-[15px]">
          {SECTION_LABELS.map(([key, label]) => (
            <li key={key} className="flex justify-between gap-3">
              <span className="text-ink-500">{label}</span>
              <span className="tabular font-medium text-ink-900" data-testid={`count-${key}`}>
                {preview.counts[key] ?? 0}
              </span>
            </li>
          ))}
        </ul>

        <p className="text-sm text-ink-500">Данные ещё не импортированы.</p>

        <div className="flex gap-3 rounded-xl border border-warn/30 bg-warn-soft p-4 text-[15px] text-ink-900">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warn" strokeWidth={1.75} />
          <p>
            Восстановление резервной копии заменит текущие данные приложения. Если что-то пойдёт не
            так, текущие данные останутся без изменений.
          </p>
        </div>

        {error && <p className="text-sm text-danger">{error}</p>}

        <div className="flex justify-end gap-3">
          <Button type="button" variant="secondary" onClick={onClose}>
            Отмена
          </Button>
          <Button type="button" variant="danger" disabled={restore.isPending} onClick={() => restore.mutate()}>
            {restore.isPending ? "Восстановление…" : "Восстановить"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
