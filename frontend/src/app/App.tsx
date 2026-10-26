import { BrowserRouter, Route, Routes } from "react-router-dom";

import { Providers } from "@/app/providers";
import { Layout } from "@/app/Layout";
import { AccountsPage } from "@/features/accounts/AccountsPage";
import { AnalyticsPage } from "@/features/analytics/AnalyticsPage";
import { AssistantPage } from "@/features/assistant/AssistantPage";
import { BudgetsPage } from "@/features/budgets/BudgetsPage";
import { CategoriesPage } from "@/features/categories/CategoriesPage";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { DataTransferPage } from "@/features/dataTransfer/DataTransferPage";
import { DebtsPage } from "@/features/debts/DebtsPage";
import { GoalsPage } from "@/features/goals/GoalsPage";
import { NotificationsPage } from "@/features/notifications/NotificationsPage";
import { DebtDetailPage } from "@/features/debts/DebtDetailPage";
import { RecurringPage } from "@/features/recurring/RecurringPage";
import { TransactionsPage } from "@/features/transactions/TransactionsPage";

export function App() {
  return (
    <Providers>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<DashboardPage />} />
            <Route path="accounts" element={<AccountsPage />} />
            <Route path="transactions" element={<TransactionsPage />} />
            <Route path="analytics" element={<AnalyticsPage />} />
            <Route path="assistant" element={<AssistantPage />} />
            <Route path="budgets" element={<BudgetsPage />} />
            <Route path="goals" element={<GoalsPage />} />
            <Route path="recurring" element={<RecurringPage />} />
            <Route path="debts" element={<DebtsPage />} />
            <Route path="debts/:debtId" element={<DebtDetailPage />} />
            <Route path="notifications" element={<NotificationsPage />} />
            <Route path="categories" element={<CategoriesPage />} />
            <Route path="data" element={<DataTransferPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </Providers>
  );
}
