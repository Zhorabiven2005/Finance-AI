/**
 * Быстрые периоды для фильтра операций и аналитики.
 *
 * Границы считаются в локальном времени браузера (начало/конец суток), а
 * в API уходят уже как UTC ISO — так операция, попавшая в "Сегодня", это
 * ровно то, что пользователь считает сегодняшним днём, а не днём по UTC.
 */

export type PeriodPreset = "all" | "today" | "7d" | "this_month" | "last_month" | "3m" | "custom";

export interface PeriodRange {
  from: Date;
  to: Date;
}

// "all" (без фильтра по периоду) есть только у журнала операций — это его
// состояние по умолчанию и то, куда возвращает "Сбросить фильтры".
// Аналитике период нужен всегда, поэтому на её странице этот пресет не
// используется (см. presets на AnalyticsPage).
export const PERIOD_PRESETS: PeriodPreset[] = [
  "all",
  "today",
  "7d",
  "this_month",
  "last_month",
  "3m",
  "custom",
];

export const PERIOD_PRESET_LABEL: Record<PeriodPreset, string> = {
  all: "Всё время",
  today: "Сегодня",
  "7d": "7 дней",
  this_month: "Этот месяц",
  last_month: "Прошлый месяц",
  "3m": "3 месяца",
  custom: "Свой период",
};

function startOfDay(d: Date): Date {
  const r = new Date(d);
  r.setHours(0, 0, 0, 0);
  return r;
}

function endOfDay(d: Date): Date {
  const r = new Date(d);
  r.setHours(23, 59, 59, 999);
  return r;
}

/** Возвращает диапазон дат для пресета. Для "custom" — null, если обе
 * даты ещё не выбраны пользователем. */
export function computePeriod(
  preset: PeriodPreset,
  custom?: { from: string; to: string },
): PeriodRange | null {
  const now = new Date();
  switch (preset) {
    case "all":
      return null;
    case "today":
      return { from: startOfDay(now), to: endOfDay(now) };
    case "7d": {
      const from = new Date(now);
      from.setDate(from.getDate() - 6);
      return { from: startOfDay(from), to: endOfDay(now) };
    }
    case "this_month": {
      const from = new Date(now.getFullYear(), now.getMonth(), 1);
      const to = new Date(now.getFullYear(), now.getMonth() + 1, 0);
      return { from: startOfDay(from), to: endOfDay(to) };
    }
    case "last_month": {
      const from = new Date(now.getFullYear(), now.getMonth() - 1, 1);
      const to = new Date(now.getFullYear(), now.getMonth(), 0);
      return { from: startOfDay(from), to: endOfDay(to) };
    }
    case "3m": {
      const from = new Date(now);
      from.setDate(from.getDate() - 91);
      return { from: startOfDay(from), to: endOfDay(now) };
    }
    case "custom": {
      if (!custom?.from || !custom?.to) return null;
      const from = new Date(`${custom.from}T00:00:00`);
      const to = new Date(`${custom.to}T00:00:00`);
      if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) return null;
      return { from: startOfDay(from), to: endOfDay(to) };
    }
  }
}

export function periodToApiParams(range: PeriodRange): { date_from: string; date_to: string } {
  return { date_from: range.from.toISOString(), date_to: range.to.toISOString() };
}
