import { useEffect, useState } from "react";

/** Возвращает value с задержкой delayMs — не дёргает API на каждый
 * нажатый символ поиска. */
export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
