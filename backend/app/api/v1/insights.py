"""Финансовые инсайты (Stage 3C).

  * GET /api/v1/insights?period=current_month|previous_month|last_3_months —
    посчитанные выводы; read-only сессия, модель не участвует, поэтому
    работает и без Ollama;
  * GET /api/v1/insights/warnings — актуальные финансовые предупреждения
    (Stage 3E), тоже только чтение и без модели;
  * POST /api/v1/insights/explain — объяснение одного вывода локальной
    моделью потоком NDJSON (те же события и та же сверка чисел, что у чата).
    Инсайт пересчитывается заново на сервере: от клиента приходит только его
    id и период, никакого текста для модели.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import clock
from app.api.v1.assistant import STATE_MESSAGES, get_ollama_client
from app.assistant.chat import stream_events
from app.assistant.generation import ChatStream
from app.assistant.ollama import OllamaClient
from app.assistant.prompts import build_messages
from app.config import settings
from app.db.readonly import get_readonly_db
from app.insights.builder import build_insights
from app.insights.warnings import build_warnings
from app.insights.explain import COMPARISON_ID_PREFIX, EXPLAIN_REQUEST, comparison_facts_text, facts_text
from app.schemas.insights import InsightExplainRequest, InsightPeriodKey, InsightsOut, WarningsOut

router = APIRouter(prefix="/insights", tags=["insights"])


def _build(db: Session, period: InsightPeriodKey) -> InsightsOut:
    return build_insights(
        db, period_key=period, today=clock.today(), today_utc=clock.utc_today(), now=datetime.now(timezone.utc)
    )


@router.get("", response_model=InsightsOut)
def get_insights(
    period: Annotated[InsightPeriodKey, Query()] = "current_month",
    db: Session = Depends(get_readonly_db),
) -> InsightsOut:
    return _build(db, period)


@router.get("/warnings", response_model=WarningsOut)
def get_warnings(db: Session = Depends(get_readonly_db)) -> WarningsOut:
    """Актуальные финансовые предупреждения (Stage 3E): только чтение, без
    модели; повторы исключены стабильными ключами (см. app/insights/warnings.py)."""
    return build_warnings(db, today=clock.today(), today_utc=clock.utc_today(), now=datetime.now(timezone.utc))


@router.post("/explain")
def explain_insight(
    payload: InsightExplainRequest,
    db: Session = Depends(get_readonly_db),
    client: OllamaClient = Depends(get_ollama_client),
) -> StreamingResponse:
    if not settings.assistant_enabled:
        raise HTTPException(status_code=503, detail=STATE_MESSAGES["disabled"])
    built = _build(db, payload.period)
    facts = None
    if payload.insight_id.startswith(COMPARISON_ID_PREFIX) and built.comparison is not None:
        currency = payload.insight_id.removeprefix(COMPARISON_ID_PREFIX)
        item = next((c for c in built.comparison.by_currency if c.currency == currency), None)
        if item is not None:
            facts = comparison_facts_text(built.comparison, item)
    else:
        insight = next((i for i in built.insights if i.id == payload.insight_id), None)
        if insight is not None:
            facts = facts_text(insight)
    if facts is None:
        raise HTTPException(status_code=404, detail="Такого вывода за этот период нет — обновите список инсайтов.")
    stream = ChatStream(
        client,
        model=settings.assistant_model,
        messages=build_messages(facts, [{"role": "user", "content": EXPLAIN_REQUEST}]),
        max_output_tokens=settings.assistant_max_output_tokens,
        context_window_tokens=settings.assistant_context_window_tokens,
        max_output_chars=settings.assistant_max_output_chars,
        chunk_timeout=settings.assistant_chunk_timeout_seconds,
        total_timeout=settings.assistant_total_timeout_seconds,
    )
    meta = {"insight_id": payload.insight_id, "context_generated_at": datetime.now(timezone.utc).isoformat()}
    return StreamingResponse(
        stream_events(stream, model=settings.assistant_model, meta=meta, grounding_sources=[facts]),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
