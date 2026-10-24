import type { TopExpenseItem } from "@/lib/api/analytics";
import { EmptyState } from "@/components/ui/Card";
import { CategoryIcon } from "@/lib/categoryIcons";
import { formatMoney } from "@/lib/money";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function TopExpensesList({
  items,
  onSelect,
}: {
  items: TopExpenseItem[];
  onSelect: (transactionId: number) => void;
}) {
  if (items.length === 0) {
    return <EmptyState>Расходов за период не было.</EmptyState>;
  }

  return (
    <ul className="divide-y divide-border">
      {items.map((item) => (
        <li key={item.transaction_id}>
          <button
            type="button"
            onClick={() => onSelect(item.transaction_id)}
            className="flex w-full items-center gap-3 py-3.5 text-left transition-colors first:pt-0 last:pb-0 hover:bg-surface-hover"
          >
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-hover text-ink-500">
              <CategoryIcon name={item.category_name} type="expense" icon={item.category_icon} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[15px] font-medium text-ink-900">
                {item.category_name}
                {item.comment && <span className="font-normal text-ink-500"> · {item.comment}</span>}
              </span>
              <span className="block text-sm text-ink-500">
                {item.account_name} · {formatDate(item.occurred_at)}
              </span>
            </span>
            <span className="tabular shrink-0 text-[15px] font-semibold text-ink-900">
              {formatMoney(item.amount)}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
