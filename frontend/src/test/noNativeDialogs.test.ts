/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";

// Исходники приложения как текст (без тестов): защита от возврата системных
// alert/confirm/prompt в пользовательские сценарии.
const sources = import.meta.glob<string>(["/src/**/*.{ts,tsx}", "!/src/**/*.test.{ts,tsx}", "!/src/test/**"], {
  query: "?raw",
  import: "default",
  eager: true,
});

const NATIVE_DIALOG = /(^|[^\w.]|window\.)(alert|confirm|prompt)\s*\(/;

function withoutComments(code: string): string {
  return code.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
}

describe("Нативные диалоги браузера", () => {
  it("исходники найдены", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(30);
  });

  it("не используются в коде приложения", () => {
    const offenders = Object.entries(sources)
      .flatMap(([file, code]) =>
        withoutComments(code)
          .split("\n")
          .map((line, i) => ({ file, line: i + 1, text: line.trim() }))
          .filter(({ text }) => NATIVE_DIALOG.test(text)),
      )
      .map(({ file, line, text }) => `${file}:${line} ${text}`);
    expect(offenders).toEqual([]);
  });
});
