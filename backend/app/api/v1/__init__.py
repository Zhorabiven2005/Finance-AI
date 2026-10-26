"""Роутеры версии v1."""

from fastapi import APIRouter

from app.api.v1 import (
    accounts,
    analytics,
    assistant,
    budgets,
    categories,
    context,
    dashboard,
    data_transfer,
    debts,
    goals,
    health,
    insights,
    notifications,
    recurring_transactions,
    settings,
    transactions,
    transfers,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(settings.router)
api_router.include_router(accounts.router)
api_router.include_router(categories.router)
api_router.include_router(transactions.router)
api_router.include_router(transfers.router)
api_router.include_router(debts.router)
api_router.include_router(dashboard.router)
api_router.include_router(analytics.router)
api_router.include_router(budgets.router)
api_router.include_router(recurring_transactions.router)
api_router.include_router(goals.router)
api_router.include_router(data_transfer.router)
api_router.include_router(notifications.router)
api_router.include_router(context.router)
api_router.include_router(assistant.router)
api_router.include_router(insights.router)

__all__ = ["api_router"]
