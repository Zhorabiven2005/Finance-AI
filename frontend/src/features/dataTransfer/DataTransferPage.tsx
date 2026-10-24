import { useQueryClient } from "@tanstack/react-query";
import { DatabaseBackup, Download, FileSpreadsheet, Upload } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { errorMessage } from "@/lib/api/client";
import {
  dataTransferApi,
  EXPORTS,
  fileToBase64,
  type BackupPreview,
  type CsvCommitResult,
} from "@/lib/api/dataTransfer";

import { BackupRestoreModal } from "./BackupRestoreModal";
import { CsvImportModal } from "./CsvImportModal";

const MB = 1024 * 1024;
const MAX_BACKUP_BYTES = 25 * MB;
const MAX_CSV_BYTES = 5 * MB;

function Action({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 py-4 first:pt-0 last:pb-0">
      <div className="min-w-0 max-w-xl">
        <p className="text-[15px] font-medium text-ink-900">{title}</p>
        <p className="text-sm text-ink-500">{description}</p>
      </div>
      <div className="flex shrink-0 gap-2">{children}</div>
    </div>
  );
}

type Notice = { title: string; text: string };

export function DataTransferPage() {
  const queryClient = useQueryClient();
  const backupInput = useRef<HTMLInputElement>(null);
  const csvInput = useRef<HTMLInputElement>(null);

  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [backup, setBackup] = useState<{ file: File; preview: BackupPreview } | null>(null);
  const [csv, setCsv] = useState<{ file: File; base64: string } | null>(null);

  const fail = (title: string, err: unknown) => setNotice({ title, text: errorMessage(err) });

  const download = async (key: keyof typeof EXPORTS) => {
    setBusy(key);
    try {
      await dataTransferApi.downloadExport(EXPORTS[key]);
    } catch (err) {
      fail("Не удалось скачать файл", err);
    } finally {
      setBusy(null);
    }
  };

  const onBackupSelected = async (file: File | undefined) => {
    if (backupInput.current) backupInput.current.value = "";
    if (!file) return;
    if (file.size > MAX_BACKUP_BYTES) {
      setNotice({ title: "Файл слишком большой", text: "Резервная копия может весить не больше 25 МБ." });
      return;
    }
    setBusy("restore");
    try {
      setBackup({ file, preview: await dataTransferApi.previewBackup(file) });
    } catch (err) {
      fail("Не удалось проверить файл", err);
    } finally {
      setBusy(null);
    }
  };

  const onCsvSelected = async (file: File | undefined) => {
    if (csvInput.current) csvInput.current.value = "";
    if (!file) return;
    if (file.size > MAX_CSV_BYTES) {
      setNotice({ title: "Файл слишком большой", text: "CSV-файл может весить не больше 5 МБ." });
      return;
    }
    try {
      setCsv({ file, base64: await fileToBase64(file) });
    } catch (err) {
      fail("Не удалось прочитать файл", err);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-[28px] font-semibold tracking-tight text-ink-900">Импорт и экспорт</h1>

      <Card>
        <CardHeader title="Резервная копия" />
        <div className="divide-y divide-border">
          <Action
            title="Экспортировать данные"
            description="Скачать полную резервную копию Finance AI в JSON: счета, категории, операции, переводы, долги, бюджеты, регулярные операции и цели."
          >
            <Button variant="secondary" disabled={busy === "backup"} onClick={() => download("backup")}>
              <DatabaseBackup className="h-4 w-4" strokeWidth={1.75} />
              Скачать backup
            </Button>
          </Action>
          <Action
            title="Восстановить из резервной копии"
            description="Файл сначала проверяется, затем показывается, что в нём. Текущие данные будут заменены только после подтверждения."
          >
            <Button variant="secondary" disabled={busy === "restore"} onClick={() => backupInput.current?.click()}>
              <Upload className="h-4 w-4" strokeWidth={1.75} />
              {busy === "restore" ? "Проверка…" : "Восстановить из backup"}
            </Button>
            <input
              ref={backupInput}
              type="file"
              accept=".json,application/json"
              className="hidden"
              aria-label="Файл резервной копии"
              onChange={(e) => onBackupSelected(e.target.files?.[0])}
            />
          </Action>
        </div>
      </Card>

      <Card>
        <CardHeader title="Операции" />
        <div className="divide-y divide-border">
          <Action
            title="Экспорт операций CSV"
            description="Доходы и расходы в таблице для Excel: дата, сумма, счёт, категория, комментарий, долг."
          >
            <Button variant="secondary" disabled={busy === "transactions"} onClick={() => download("transactions")}>
              <Download className="h-4 w-4" strokeWidth={1.75} />
              Скачать CSV
            </Button>
          </Action>
          <Action
            title="Импорт операций из CSV"
            description="Добавляет операции к текущим данным. Перед импортом — проверка, сопоставление колонок и защита от повторов."
          >
            <Button variant="secondary" onClick={() => csvInput.current?.click()}>
              <Upload className="h-4 w-4" strokeWidth={1.75} />
              Импортировать CSV
            </Button>
            <input
              ref={csvInput}
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              aria-label="CSV-файл с операциями"
              onChange={(e) => onCsvSelected(e.target.files?.[0])}
            />
          </Action>
        </div>
      </Card>

      <Card>
        <CardHeader title="Другие таблицы" />
        <Action title="Экспорт в CSV" description="Отдельные таблицы для просмотра в Excel. Для восстановления используйте резервную копию.">
          {(
            [
              ["accounts", "Счета"],
              ["transfers", "Переводы"],
              ["debts", "Долги"],
              ["goals", "Цели"],
            ] as const
          ).map(([key, label]) => (
            <Button key={key} variant="ghost" size="sm" disabled={busy === key} onClick={() => download(key)}>
              <FileSpreadsheet className="h-4 w-4" strokeWidth={1.75} />
              {label}
            </Button>
          ))}
        </Action>
      </Card>

      {backup && (
        <BackupRestoreModal
          file={backup.file}
          preview={backup.preview}
          onClose={() => setBackup(null)}
          onRestored={() => {
            setBackup(null);
            queryClient.invalidateQueries();
            setNotice({ title: "Данные восстановлены", text: "Состояние приложения восстановлено из резервной копии." });
          }}
        />
      )}
      {csv && (
        <CsvImportModal
          file={csv.file}
          fileBase64={csv.base64}
          onClose={() => setCsv(null)}
          onImported={(result: CsvCommitResult) => {
            setCsv(null);
            queryClient.invalidateQueries();
            const parts = [`Добавлено операций: ${result.created}`];
            if (result.duplicates_skipped) parts.push(`пропущено повторов: ${result.duplicates_skipped}`);
            if (result.created_accounts) parts.push(`создано счетов: ${result.created_accounts}`);
            if (result.created_categories) parts.push(`создано категорий: ${result.created_categories}`);
            setNotice({ title: "Импорт завершён", text: parts.join(", ") + "." });
          }}
        />
      )}
      {notice && (
        <ConfirmModal title={notice.title} onClose={() => setNotice(null)}>
          {notice.text}
        </ConfirmModal>
      )}
    </div>
  );
}
