"""Финансовый контекст (Stage 2F): GET /api/v1/context.

Только GET и только через сессию для чтения (app/db/readonly.py): эндпоинт
не может изменить финансовые данные, не создаёт уведомления и не
обрабатывает регулярные операции. Структура ответа и формулы —
docs/financial-context.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import clock
# Импорт модуля, а не имени: builder сам импортирует app.api.v1.* (to_out
# счетов, долгов, бюджетов, целей), и импорт имени дал бы цикл, если первым
# загружается app.context.builder.
from app.context import builder as context_builder
from app.db.readonly import get_readonly_db
from app.schemas.context import FINANCIAL_CONTEXT_VERSION, ContextSchemaOut, FinancialContextOut

router = APIRouter(prefix="/context", tags=["context"])

DEFAULT_MONTHS = 6
DEFAULT_UPCOMING_DAYS = 30


@router.get("", response_model=FinancialContextOut)
def get_context(
    months: Annotated[int, Query(ge=1, le=24, description="Полных календарных месяцев (UTC) в окне показателей")] = DEFAULT_MONTHS,
    upcoming_days: Annotated[int, Query(ge=1, le=90, description="Горизонт предстоящих событий, дней")] = DEFAULT_UPCOMING_DAYS,
    db: Session = Depends(get_readonly_db),
) -> FinancialContextOut:
    return context_builder.build_context(
        db,
        months=months,
        horizon_days=upcoming_days,
        today=clock.today(),
        today_utc=clock.utc_today(),
        now=datetime.now(timezone.utc),
    )


@router.get("/schema", response_model=ContextSchemaOut)
def get_context_schema() -> ContextSchemaOut:
    return ContextSchemaOut(
        schema_version=FINANCIAL_CONTEXT_VERSION,
        json_schema=FinancialContextOut.model_json_schema(),
    )
