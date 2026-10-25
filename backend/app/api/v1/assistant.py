"""Локальный AI-помощник (Stage 3A): статус Ollama и предпросмотр сводки.

  * GET /api/v1/assistant/status — БД не использует вообще; проверяет только
    локальный сервер Ollama и наличие выбранной модели;
  * GET /api/v1/assistant/context-preview — то, что в Stage 3B получит модель:
    сводка строится из read-only контекста Stage 2F (get_readonly_db), без
    собственных SQL-запросов и без записи в БД.

Ни один из эндпоинтов не отправляет финансовые данные в модель: чата в
Stage 3A нет.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import clock
from app.assistant import digest as digest_module
from app.api.v1.context import DEFAULT_MONTHS, DEFAULT_UPCOMING_DAYS
from app.assistant.ollama import OllamaClient, OllamaStatus
from app.config import settings
from app.context import builder as context_builder
from app.db.readonly import get_readonly_db
from app.schemas.assistant import (
    AssistantContextPreviewOut,
    AssistantModelOut,
    AssistantServerOut,
    AssistantStatusOut,
)

router = APIRouter(prefix="/assistant", tags=["assistant"])

STATE_MESSAGES = {
    "ready": "Локальная модель доступна, помощник готов к работе.",
    "disabled": "Помощник выключен в настройках (ASSISTANT_ENABLED=false).",
    "server_unreachable": "Ollama не отвечает. Запустите Ollama и проверьте снова.",
    "server_timeout": "Ollama не ответил вовремя. Возможно, он ещё запускается — проверьте снова через минуту.",
    "server_bad_response": "По адресу Ollama отвечает другой сервер или ответ некорректен. Проверьте ASSISTANT_OLLAMA_URL.",
    "model_not_found": "Модель не найдена в Ollama. Загрузите её командой: ollama pull {model}",
    "model_not_local": "Выбранная модель облачная. Помощник работает только с локальными моделями.",
}


def get_ollama_client() -> OllamaClient:
    """Зависимость: в тестах подменяется клиентом фейкового сервера."""
    return OllamaClient(settings.assistant_ollama_url, settings.assistant_status_timeout_seconds)


def _status_out(enabled: bool, client: OllamaClient, model_name: str, result: OllamaStatus | None) -> AssistantStatusOut:
    state = "disabled" if result is None else result.state
    info = result.model if result else None
    return AssistantStatusOut(
        enabled=enabled,
        provider="ollama",
        state=state,
        ready=state == "ready",
        message=STATE_MESSAGES[state].format(model=model_name),
        server=AssistantServerOut(
            url=client.base_url,
            available=bool(result and result.server_reachable),
            version=result.server_version if result else None,
        ),
        model=AssistantModelOut(
            name=model_name,
            available=info is not None,
            local=(not info.remote) if info else None,
            size_bytes=info.size_bytes if info else None,
            parameter_size=info.parameter_size if info else None,
            quantization=info.quantization if info else None,
        ),
        checked_at=datetime.now(timezone.utc),
    )


@router.get("/status", response_model=AssistantStatusOut)
def assistant_status(client: OllamaClient = Depends(get_ollama_client)) -> AssistantStatusOut:
    model_name = settings.assistant_model
    if not settings.assistant_enabled:
        return _status_out(False, client, model_name, None)
    return _status_out(True, client, model_name, client.check(model_name))


@router.get("/context-preview", response_model=AssistantContextPreviewOut)
def assistant_context_preview(
    months: Annotated[int, Query(ge=1, le=24)] = DEFAULT_MONTHS,
    upcoming_days: Annotated[int, Query(ge=1, le=90)] = DEFAULT_UPCOMING_DAYS,
    db: Session = Depends(get_readonly_db),
) -> AssistantContextPreviewOut:
    ctx = context_builder.build_context(
        db,
        months=months,
        horizon_days=upcoming_days,
        today=clock.today(),
        today_utc=clock.utc_today(),
        now=datetime.now(timezone.utc),
    )
    digest = digest_module.build_digest(ctx)
    budget = settings.assistant_digest_token_budget
    text, tokens, omitted = digest_module.render_digest_text(digest, budget)
    return AssistantContextPreviewOut(
        digest=digest, text=text, estimated_tokens=tokens, token_budget=budget, omitted_sections=omitted
    )
