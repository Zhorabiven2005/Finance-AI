import { Banknote, Landmark, Wallet } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { AccountType } from "@/lib/api/accounts";

const ACCOUNT_TYPE_ICON: Record<AccountType, LucideIcon> = {
  bank: Landmark,
  cash: Wallet,
  other: Banknote,
};

export function AccountTypeIcon({
  type,
  className = "h-4 w-4",
}: {
  type: AccountType;
  className?: string;
}) {
  const Icon = ACCOUNT_TYPE_ICON[type];
  return <Icon className={className} strokeWidth={1.75} aria-hidden />;
}
