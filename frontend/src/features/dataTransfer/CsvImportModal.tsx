import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { accountsApi } from "@/lib/api/accounts";
import { categoriesApi } from "@/lib/api/categories";
import { errorMessage } from "@/lib/api/client";
import {
  dataTransferApi,
  type CsvCommitResult,
  type CsvField,
  type CsvImportOptions,
  type CsvPreview,
  type CsvRowSample,
  type Resolution,
} from "@/lib/api/dataTransfer";
import { formatMoney } from "@/lib/money";

const STATUS_LABEL: Record<CsvRowSample["status"], string> = {
  new: "Новая",
  duplicate: "Уже есть",
  skipped: "Пропущена",
  error: "Ошибка",
};

const STATUS_CLASS: Record<CsvRowSample["status"], string> = {
  new: "text-success",
  duplicate: "text-ink-500",
  skipped: "text-ink-500",
  error: "text-danger",
};

function resolutionValue(r: Resolution | undefined): string {
  if (!r) return "";
  return r.action === "create" ? "create" : `map:${r.target_id}`;
}

function parseResolution(value: string): Resolution | null {
  if (value === "create") return { action: "create" };
  if (value.startsWith("map:")) return { action: "map", target_id: Number(value.slice(4)) };
  return null;
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="rounded-xl border border-border bg-page/60 px-4 py-3">
      <p className="text-sm text-ink-500">{label}</p>
      <p className={`tabular text-xl font-semibold ${tone ?? "text-ink-900"}`}>{value}</p>
    </div>
  );
}

export function CsvImportModal({
  file,
  fileBase64,
  onClose,
  onImported,
}: {
  file: File;
  fileBase64: string;
  onClose: () => void;
  onImported: (result: CsvCommitResult) => void;
}) {
  const [options, setOptions] = useState<CsvImportOptions>({
    mapping: null,
    tz_offset_minutes: new Date().getTimezoneOffset(),
    account_resolutions: {},
    category_resolutions: {},
  });
  const [commitError, setCommitError] = useState<string | null>(null);

  const fileId = `${file.name}:${file.size}:${file.lastModified}`;
  const previewQuery = useQuery({
    queryKey: ["csv-preview", fileId, options],
    queryFn: () => dataTransferApi.previewCsv(fileBase64, options),
    placeholderData: keepPreviousData,
    staleTime: 0,
    gcTime: 0,
  });
  const preview: CsvPreview | undefined = previewQuery.data;

  const { data: accounts } = useQuery({
    queryKey: ["accounts", "with-inactive"],
    queryFn: () => accountsApi.list(true),
  });
  const { data: categories } = useQuery({
    queryKey: ["categories", "all-including-archived"],
    queryFn: () => categoriesApi.list({ includeArchived: true }),
  });

  const commit = useMutation({
    mutationFn: () => dataTransferApi.commitCsv(fileBase64, options),
    onSuccess: onImported,
    onError: (err) => setCommitError(errorMessage(err, "Импорт не выполнен")),
  });

  const setMapping = (field: CsvField, column: string) => {
    if (!preview) return;
    setOptions((o) => ({ ...o, mapping: { ...preview.mapping, [field]: column || null } }));
  };

  const setResolution = (kind: "account_resolutions" | "category_resolutions", key: string, value: string) => {
    setOptions((o) => {
      const next = { ...(o[kind] ?? {}) };
      const parsed = parseResolution(value);
      if (parsed) next[key] = parsed;
      else delete next[key];
      return { ...o, [kind]: next };
    });
  };

  if (previewQuery.isError && !preview) {
    return (
      <Modal title="Не удалось прочитать CSV" onClose={onClose} size="lg">
        <div className="flex flex-col gap-5">
          <p className="rounded-xl border border-danger/25 bg-danger-soft p-4 text-[15px] text-danger">
            {errorMessage(previewQuery.error, "Файл не удалось разобрать")}
          </p>
          <p className="text-sm text-ink-500">Данные не изменены.</p>
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
    <Modal title={`Импорт операций: ${file.name}`} onClose={onClose} size="xl">
      {!preview ? (
        <p className="text-[15px] text-ink-500">Проверяем файл…</p>
      ) : (
        <div className="flex flex-col gap-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Stat label="Всего строк" value={preview.total_rows} />
            <Stat label="Будут добавлены" value={preview.new_rows} tone="text-success" />
            <Stat label="Уже есть (дубли)" value={preview.duplicate_rows} />
            <Stat label="Пропущено" value={preview.skipped_rows} />
            <Stat label="Ошибок" value={preview.error_rows} tone={preview.error_rows ? "text-danger" : "text-ink-900"} />
          </div>

          <section>
            <h3 className="mb-3 text-[15px] font-semibold text-ink-900">Сопоставление колонок</h3>
            <div className="grid gap-3 md:grid-cols-2">
              {preview.fields.map((f) => (
                <label key={f.key} className="flex items-center gap-3 text-[15px]">
                  <span className="w-48 shrink-0 text-ink-500">
                    {f.label}
                    {f.required && <span className="text-danger"> *</span>}
                  </span>
                  <Select
                    aria-label={`Колонка для поля «${f.label}»`}
                    value={preview.mapping[f.key] ?? ""}
                    onChange={(e) => setMapping(f.key, e.target.value)}
                  >
                    <option value="">— не сопоставлено —</option>
                    {preview.headers.map((h) => (
                      <option key={h} value={h}>
                        {h}
                      </option>
                    ))}
                  </Select>
                </label>
              ))}
              {!preview.mapping.account && (
                <label className="flex items-center gap-3 text-[15px]">
                  <span className="w-48 shrink-0 text-ink-500">Счёт для всех строк</span>
                  <Select
                    aria-label="Счёт для всех строк"
                    value={options.default_account_id ?? ""}
                    onChange={(e) =>
                      setOptions((o) => ({
                        ...o,
                        default_account_id: e.target.value ? Number(e.target.value) : null,
                      }))
                    }
                  >
                    <option value="">— выберите счёт —</option>
                    {(accounts ?? []).map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name} ({a.currency})
                      </option>
                    ))}
                  </Select>
                </label>
              )}
            </div>
            {preview.mapping_errors.length > 0 && (
              <ul className="mt-3 flex flex-col gap-1 text-sm text-danger">
                {preview.mapping_errors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            )}
          </section>

          {preview.skipped_rows > 0 && (
            <p className="text-sm text-ink-500">
              Пропущено строк: {preview.skipped_rows} — это погашения долгов. Они связаны с долгом и
              переносятся только через резервную копию.
            </p>
          )}

          {(preview.unknown_accounts.length > 0 || preview.unknown_categories.length > 0) && (
            <section>
              <h3 className="mb-1 text-[15px] font-semibold text-ink-900">Не найдены в приложении</h3>
              <p className="mb-3 text-sm text-ink-500">
                Новые счета и категории не создаются автоматически — выберите, что делать с каждым.
              </p>
              <div className="flex flex-col gap-3">
                {preview.unknown_accounts.map((a) => (
                  <label key={a.key} className="flex flex-wrap items-center gap-3 text-[15px]">
                    <span className="w-64 text-ink-900">
                      Счёт «{a.name}» <span className="text-ink-500">({a.rows} стр.)</span>
                    </span>
                    <Select
                      aria-label={`Счёт «${a.name}»`}
                      className="max-w-sm"
                      value={resolutionValue(options.account_resolutions?.[a.key])}
                      onChange={(e) => setResolution("account_resolutions", a.key, e.target.value)}
                    >
                      <option value="">— выберите —</option>
                      <option value="create">Создать новый счёт «{a.name}»</option>
                      {(accounts ?? []).map((acc) => (
                        <option key={acc.id} value={`map:${acc.id}`}>
                          Использовать «{acc.name}» ({acc.currency})
                        </option>
                      ))}
                    </Select>
                  </label>
                ))}
                {preview.unknown_categories.map((c) => (
                  <label key={c.key} className="flex flex-wrap items-center gap-3 text-[15px]">
                    <span className="w-64 text-ink-900">
                      Категория «{c.name}»{" "}
                      <span className="text-ink-500">
                        ({c.type === "income" ? "доход" : "расход"}, {c.rows} стр.)
                      </span>
                    </span>
                    <Select
                      aria-label={`Категория «${c.name}»`}
                      className="max-w-sm"
                      value={resolutionValue(options.category_resolutions?.[c.key])}
                      onChange={(e) => setResolution("category_resolutions", c.key, e.target.value)}
                    >
                      <option value="">— выберите —</option>
                      <option value="create">Создать новую категорию «{c.name}»</option>
                      {(categories ?? [])
                        .filter((cat) => cat.type === c.type)
                        .map((cat) => (
                          <option key={cat.id} value={`map:${cat.id}`}>
                            Использовать «{cat.name}»
                          </option>
                        ))}
                    </Select>
                  </label>
                ))}
              </div>
            </section>
          )}

          {preview.errors.length > 0 && (
            <section>
              <h3 className="mb-3 text-[15px] font-semibold text-ink-900">Ошибки в файле</h3>
              <ul className="flex max-h-48 flex-col gap-1 overflow-y-auto rounded-xl border border-danger/25 bg-danger-soft p-4 text-sm text-danger">
                {preview.errors.map((e, i) => (
                  <li key={`${e.row}-${i}`}>
                    Строка {e.row}: {e.message}
                  </li>
                ))}
              </ul>
              {preview.errors_total > preview.errors.length && (
                <p className="mt-2 text-sm text-ink-500">
                  Показаны первые {preview.errors.length} из {preview.errors_total}.
                </p>
              )}
            </section>
          )}

          {preview.sample.length > 0 && (
            <section>
              <h3 className="mb-3 text-[15px] font-semibold text-ink-900">Первые строки</h3>
              <div className="overflow-x-auto rounded-xl border border-border">
                <table className="w-full text-left text-sm">
                  <thead className="bg-page text-ink-500">
                    <tr>
                      <th className="px-3 py-2 font-medium">Стр.</th>
                      <th className="px-3 py-2 font-medium">Дата</th>
                      <th className="px-3 py-2 text-right font-medium">Сумма</th>
                      <th className="px-3 py-2 font-medium">Счёт</th>
                      <th className="px-3 py-2 font-medium">Категория</th>
                      <th className="px-3 py-2 font-medium">Комментарий</th>
                      <th className="px-3 py-2 font-medium">Статус</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {preview.sample.map((r) => (
                      <tr key={r.row}>
                        <td className="px-3 py-2 text-ink-500">{r.row}</td>
                        <td className="px-3 py-2 text-ink-900">
                          {r.occurred_at ? new Date(r.occurred_at).toLocaleString("ru-RU") : "—"}
                        </td>
                        <td className="tabular px-3 py-2 text-right text-ink-900">
                          {r.amount_minor !== null && r.currency
                            ? `${r.type === "income" ? "+" : "−"}${formatMoney({ minor: r.amount_minor, currency: r.currency })}`
                            : "—"}
                        </td>
                        <td className="px-3 py-2 text-ink-900">{r.account ?? "—"}</td>
                        <td className="px-3 py-2 text-ink-900">{r.category ?? "—"}</td>
                        <td className="max-w-[220px] truncate px-3 py-2 text-ink-500">{r.comment ?? ""}</td>
                        <td className={`px-3 py-2 font-medium ${STATUS_CLASS[r.status]}`}>
                          {STATUS_LABEL[r.status]}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <p className="text-[15px] text-ink-500">
            Импорт добавит новые операции в текущие данные. Повторяющиеся операции будут пропущены.
            {!preview.can_import && preview.new_rows > 0 && " Исправьте ошибки, чтобы продолжить."}
            {preview.new_rows === 0 && preview.error_rows === 0 && " Новых операций нет."}
          </p>

          {commitError && <p className="text-sm text-danger">{commitError}</p>}

          <div className="flex justify-end gap-3">
            <Button type="button" variant="secondary" onClick={onClose}>
              Отмена
            </Button>
            <Button
              type="button"
              disabled={!preview.can_import || commit.isPending || previewQuery.isFetching}
              onClick={() => commit.mutate()}
            >
              {commit.isPending ? "Импорт…" : `Импортировать (${preview.new_rows})`}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
