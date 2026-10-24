/**
 * Клиентский аналог backend Money.
 *
 * Инвариант всей системы: деньги передаются и хранятся как целое число
 * минорных единиц. На фронтенде НЕТ денежной арифметики с плавающей точкой —
 * number в JS это IEEE 754 double, и 0.1 + 0.2 !== 0.3.
 *
 * Суммирование и любые расчёты выполняет backend. Здесь только форматирование
 * и разбор пользовательского ввода.
 */

export interface Currency {
  code: string;
  exponent: number;
  symbol: string;
  name: string;
}

/** Денежная сумма в том виде, в каком её отдаёт API. */
export interface MoneyAmount {
  minor: number;
  currency: string;
}

export const RUB: Currency = {
  code: "RUB",
  exponent: 2,
  symbol: "\u20bd",
  name: "Российский рубль",
};

const CURRENCY_REGISTRY: Record<string, Currency> = {
  RUB,
  USD: { code: "USD", exponent: 2, symbol: "$", name: "US Dollar" },
  EUR: { code: "EUR", exponent: 2, symbol: "EUR", name: "Euro" },
  KZT: { code: "KZT", exponent: 2, symbol: "KZT", name: "Kazakhstani Tenge" },
  JPY: { code: "JPY", exponent: 0, symbol: "JPY", name: "Japanese Yen" },
};

export function resolveCurrency(code: string): Currency {
  return CURRENCY_REGISTRY[code] ?? { code, exponent: 2, symbol: code, name: code };
}

function subunit(currency: Currency): number {
  return 10 ** currency.exponent;
}

/** Форматирует минорные единицы для отображения: 123456 -> "1 234,56 ₽" */
export function formatMinor(
  minor: number,
  currency: Currency = RUB,
  options: { withSymbol?: boolean; signDisplay?: "auto" | "always" } = {},
): string {
  const { withSymbol = true, signDisplay = "auto" } = options;

  if (!Number.isInteger(minor)) {
    throw new Error(`formatMinor ожидает целое число минорных единиц, получено ${minor}`);
  }

  const formatter = new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: currency.exponent,
    maximumFractionDigits: currency.exponent,
    signDisplay,
  });

  // Деление безопасно: используется только для отображения, не для расчётов.
  const body = formatter.format(minor / subunit(currency));
  return withSymbol ? `${body}\u00a0${currency.symbol}` : body;
}

/** Форматирует MoneyAmount, каким его отдаёт API: {minor, currency}. */
export function formatMoney(
  amount: MoneyAmount,
  options?: { withSymbol?: boolean; signDisplay?: "auto" | "always" },
): string {
  return formatMinor(amount.minor, resolveCurrency(amount.currency), options);
}

/**
 * Разбирает пользовательский ввод в минорные единицы.
 * Возвращает null, если строку нельзя интерпретировать как сумму.
 */
export function parseToMinor(input: string, currency: Currency = RUB): number | null {
  const cleaned = input
    .replace(/[\s\u00a0\u202f]/g, "")
    .replace(currency.symbol, "")
    .replace(",", ".")
    .trim();

  if (cleaned === "" || !/^-?\d*\.?\d*$/.test(cleaned)) return null;

  const negative = cleaned.startsWith("-");
  const digits = negative ? cleaned.slice(1) : cleaned;
  const [whole = "", fraction = ""] = digits.split(".");
  if (whole === "" && fraction === "") return null;

  // Работаем со строкой, а не с числом, чтобы не потерять точность.
  const paddedFraction = fraction
    .padEnd(currency.exponent, "0")
    .slice(0, currency.exponent);
  const minor = Number(`${whole || "0"}${paddedFraction}`);
  if (!Number.isSafeInteger(minor)) return null;

  return negative ? -minor : minor;
}
