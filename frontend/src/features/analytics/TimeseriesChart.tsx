import type { Granularity, TimeseriesPoint } from "@/lib/api/analytics";
import { formatMoney } from "@/lib/money";

const WIDTH = 760;
const HEIGHT = 220;
const PADDING_X = 12;
const PADDING_TOP = 12;
const PADDING_BOTTOM = 28;

const GRANULARITY_LABEL: Record<Granularity, (iso: string) => string> = {
  day: (iso) => new Date(iso).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" }),
  week: (iso) => new Date(iso).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" }),
  month: (iso) => new Date(iso).toLocaleDateString("ru-RU", { month: "short", year: "2-digit" }),
};

function buildPath(values: number[], maxValue: number): string {
  const innerWidth = WIDTH - PADDING_X * 2;
  const innerHeight = HEIGHT - PADDING_TOP - PADDING_BOTTOM;
  const step = values.length > 1 ? innerWidth / (values.length - 1) : 0;
  return values
    .map((v, i) => {
      const x = PADDING_X + step * i;
      const y = maxValue === 0 ? HEIGHT - PADDING_BOTTOM : PADDING_TOP + innerHeight * (1 - v / maxValue);
      return `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
}

export function TimeseriesChart({
  points,
  currency,
  granularity,
}: {
  points: TimeseriesPoint[];
  currency: string;
  granularity: Granularity;
}) {
  if (points.length === 0) return null;

  const incomeValues = points.map((p) => p.income.minor);
  const expenseValues = points.map((p) => p.expense.minor);
  const maxValue = Math.max(1, ...incomeValues, ...expenseValues);

  const incomePath = buildPath(incomeValues, maxValue);
  const expensePath = buildPath(expenseValues, maxValue);

  const innerWidth = WIDTH - PADDING_X * 2;
  const step = points.length > 1 ? innerWidth / (points.length - 1) : 0;

  // Не подписываем каждую точку — на месяце это 31 подпись подряд. Берём
  // разумное число меток, равномерно распределённых по оси.
  const maxLabels = 7;
  const labelEvery = Math.max(1, Math.ceil(points.length / maxLabels));
  const formatLabel = GRANULARITY_LABEL[granularity];

  return (
    <div>
      <div className="mb-3 flex items-center gap-5 text-sm">
        <span className="flex items-center gap-1.5 text-ink-500">
          <span className="h-2.5 w-2.5 rounded-full bg-success" />
          Доходы
        </span>
        <span className="flex items-center gap-1.5 text-ink-500">
          <span className="h-2.5 w-2.5 rounded-full bg-accent" />
          Расходы
        </span>
      </div>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full" role="img" aria-label="Динамика доходов и расходов">
        {[0.25, 0.5, 0.75].map((f) => (
          <line
            key={f}
            x1={PADDING_X}
            x2={WIDTH - PADDING_X}
            y1={PADDING_TOP + (HEIGHT - PADDING_TOP - PADDING_BOTTOM) * f}
            y2={PADDING_TOP + (HEIGHT - PADDING_TOP - PADDING_BOTTOM) * f}
            stroke="var(--color-border)"
            strokeWidth={1}
          />
        ))}

        <path d={expensePath} fill="none" stroke="var(--color-accent)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        <path d={incomePath} fill="none" stroke="var(--color-success)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

        {points.map((p, i) => {
          const x = PADDING_X + step * i;
          const yIncome =
            maxValue === 0
              ? HEIGHT - PADDING_BOTTOM
              : PADDING_TOP + (HEIGHT - PADDING_TOP - PADDING_BOTTOM) * (1 - p.income.minor / maxValue);
          const yExpense =
            maxValue === 0
              ? HEIGHT - PADDING_BOTTOM
              : PADDING_TOP + (HEIGHT - PADDING_TOP - PADDING_BOTTOM) * (1 - p.expense.minor / maxValue);
          return (
            <g key={p.period_start}>
              <circle cx={x} cy={yIncome} r={2.5} fill="var(--color-success)">
                <title>
                  {formatLabel(p.period_start)}: доходы {formatMoney({ minor: p.income.minor, currency })}
                </title>
              </circle>
              <circle cx={x} cy={yExpense} r={2.5} fill="var(--color-accent)">
                <title>
                  {formatLabel(p.period_start)}: расходы {formatMoney({ minor: p.expense.minor, currency })}
                </title>
              </circle>
              {i % labelEvery === 0 && (
                <text
                  x={x}
                  y={HEIGHT - 8}
                  textAnchor="middle"
                  fontSize={11}
                  fill="var(--color-ink-400)"
                >
                  {formatLabel(p.period_start)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
