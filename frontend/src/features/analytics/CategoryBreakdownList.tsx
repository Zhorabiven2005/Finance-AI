import type { CategoryBreakdownItem } from "@/lib/api/analytics";
import { EmptyState } from "@/components/ui/Card";
import { CategoryIcon } from "@/lib/categoryIcons";
import { formatMoney } from "@/lib/money";

export function CategoryBreakdownList({ items }: { items: CategoryBreakdownItem[] }) {
  if (items.length === 0) {
    return <EmptyState>Расходов за период не было.</EmptyState>;
  }

  return (
    <ul className="flex flex-col gap-4">
      {items.map((item) => (
        <li key={item.category_id}>
          <div className="mb-1.5 flex items-center justify-between gap-3">
            <span className="flex min-w-0 items-center gap-2.5 text-[15px] font-medium text-ink-900">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface-hover text-ink-500">
                <CategoryIcon name={item.category_name} type="expense" icon={item.category_icon} className="h-4 w-4" />
              </span>
              <span className="truncate">{item.category_name}</span>
            </span>
            <span className="tabular shrink-0 text-[15px] font-semibold text-ink-900">
              {formatMoney(item.amount)}{" "}
              <span className="font-normal text-ink-500">· {item.percent.toFixed(0)}%</span>
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-surface-hover">
            <div
              className="h-full rounded-full bg-accent"
              style={{ width: `${Math.min(100, item.percent)}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}
