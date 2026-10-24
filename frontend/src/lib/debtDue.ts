import type { Debt, DebtDueState } from "@/lib/api/debts";

type Tone = "neutral" | "ok" | "warn" | "danger";

function daysWord(n: number): string {
  const a = Math.abs(n);
  if (a % 10 === 1 && a % 100 !== 11) return `${a} день`;
  if (a % 10 >= 2 && a % 10 <= 4 && !(a % 100 >= 12 && a % 100 <= 14)) return `${a} дня`;
  return `${a} дней`;
}

/** Подпись и тон срока. Состояние вычисляет backend (due_state) — здесь
 * только отображение, чтобы список, карточка и Dashboard не расходились. */
export function debtDueLabel(debt: Pick<Debt, "due_state" | "days_until_due">): { label: string; tone: Tone } {
  const days = debt.days_until_due ?? 0;
  const map: Record<DebtDueState, { label: string; tone: Tone }> = {
    none: { label: "Срок не задан", tone: "neutral" },
    upcoming: { label: `Через ${daysWord(days)}`, tone: "neutral" },
    soon: { label: `Скоро: через ${daysWord(days)}`, tone: "warn" },
    today: { label: "Срок сегодня", tone: "warn" },
    overdue: { label: `Просрочен на ${daysWord(days)}`, tone: "danger" },
    paid: { label: "Погашен", tone: "ok" },
  };
  return map[debt.due_state];
}

export type DebtSort = "urgency" | "due" | "remaining";

const URGENCY: Record<DebtDueState, number> = { overdue: 0, today: 1, soon: 2, upcoming: 3, none: 4, paid: 5 };

/** Сортировка без сложных приоритетов. «Наибольший остаток» сравнивает суммы
 * только внутри одной валюты: сначала группировка по валюте. */
export function sortDebts(debts: Debt[], sort: DebtSort): Debt[] {
  const byDue = (a: Debt, b: Debt) => {
    if (a.due_date === b.due_date) return b.id - a.id;
    if (a.due_date === null) return 1;
    if (b.due_date === null) return -1;
    return a.due_date < b.due_date ? -1 : 1;
  };
  const list = [...debts];
  if (sort === "urgency") {
    return list.sort((a, b) => URGENCY[a.due_state] - URGENCY[b.due_state] || byDue(a, b));
  }
  if (sort === "due") return list.sort(byDue);
  return list.sort(
    (a, b) =>
      a.remaining.currency.localeCompare(b.remaining.currency) || b.remaining.minor - a.remaining.minor,
  );
}
