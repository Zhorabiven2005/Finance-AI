import { describe, expect, it, vi } from "vitest";

import { downloadExport, fileToBase64 } from "./dataTransfer";

describe("downloadExport", () => {
  it("скачивает файл под именем из Content-Disposition", async () => {
    const blob = new Blob(["{}"], { type: "application/json" });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(blob, {
          status: 200,
          headers: { "Content-Disposition": 'attachment; filename="finance-ai-backup-2026-10-08.json"' },
        }),
      ),
    );
    const createUrl = vi.fn(() => "blob:test");
    const revokeUrl = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL: createUrl, revokeObjectURL: revokeUrl });
    const clicked: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.download);
    });

    const name = await downloadExport("/export/backup");

    expect(fetch).toHaveBeenCalledWith("/api/v1/export/backup");
    expect(name).toBe("finance-ai-backup-2026-10-08.json");
    expect(clicked).toEqual(["finance-ai-backup-2026-10-08.json"]);
    expect(createUrl).toHaveBeenCalledTimes(1);
    expect(revokeUrl).toHaveBeenCalledWith("blob:test");
    vi.unstubAllGlobals();
  });

  it("ошибка сервера превращается в исключение, файл не скачивается", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 500 })));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click");
    await expect(downloadExport("/export/backup")).rejects.toThrow();
    expect(click).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});

describe("fileToBase64", () => {
  it("кодирует содержимое файла (включая кириллицу) без префикса data:", async () => {
    const encoded = await fileToBase64(new Blob(["Дата;Сумма"]));
    expect(new TextDecoder().decode(Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0)))).toBe("Дата;Сумма");
  });
});
