"""Проверка состояния backend и доступности базы."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings as cfg
from app.db.session import get_db
from app.schemas.common import HealthResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:  # noqa: BLE001 — статус отдаём, не падаем
        db_status = f"error: {exc.__class__.__name__}"

    return HealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        app=cfg.app_name,
        version=cfg.app_version,
        database=db_status,
        ai_configured=cfg.ai_configured,
    )
