"""Сценарий чата (Stage 3B): проверка запроса, промпт, поток событий.

Ничего не сохраняется: ни реплики, ни промпт, ни ответ не пишутся в БД, файлы
или логи. Финансовые данные берутся только из сводки Stage 3A, построенной до
начала потока (read-only сессия к этому моменту уже не нужна).

Поток событий (NDJSON, по объекту на строку):
  {"type": "meta", ...}                 — один раз в начале;
  {"type": "delta", "text": "..."}      — очередной кусок ответа;
  {"type": "done", ...}                 — успешное завершение и сверка чисел;
  {"type": "error", "code", "message"}  — ошибка; после неё поток закрывается.
"""

from __future__ import annotations

import json
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass

import anyio
from anyio import to_thread

from app.assistant.generation import ChatStream, Delta, Finished
from app.assistant.grounding import check_numbers
from app.assistant.ollama import OllamaError
from app.schemas.assistant import ChatMessageIn

# Одна генерация за раз: локальная модель на процессоре не тянет параллельные.
_GENERATION_LOCK = threading.Lock()

ERROR_MESSAGES = {
    "busy": "Помощник уже отвечает на другой вопрос. Дождитесь окончания или остановите его.",
    "server_unreachable": "Ollama не запущен. Запустите Ollama и попробуйте снова.",
    "server_timeout": "Ollama не ответил вовремя. Попробуйте снова через минуту.",
    "server_bad_response": "Ollama ответил некорректно. Проверьте адрес и версию Ollama.",
    "model_not_found": "Модель не найдена в Ollama. Загрузите её: ollama pull {model}",
    "generation_timeout": "Модель слишком долго не отвечает. Попробуйте задать вопрос короче.",
    "stream_interrupted": "Ответ модели оборвался. Попробуйте снова.",
    "generation_error": "Модель не смогла ответить. Попробуйте снова.",
    "internal_error": "Не удалось получить ответ. Попробуйте снова.",
}


class ChatValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ChatLimits:
    max_question_chars: int
    max_history_messages: int
    max_history_message_chars: int


def validate_dialogue(messages: list[ChatMessageIn], limits: ChatLimits) -> list[dict[str, str]]:
    """Проверенный диалог: последняя реплика — вопрос пользователя в пределах
    лимита; более старые реплики обрезаются по количеству (самые старые
    отбрасываются), каждая — в пределах лимита длины."""
    cleaned = [ChatMessageIn(role=m.role, content=m.content.strip()) for m in messages]
    if not cleaned or cleaned[-1].role != "user":
        raise ChatValidationError("Последним должно быть сообщение пользователя")
    question = cleaned[-1].content
    if not question:
        raise ChatValidationError("Вопрос пустой")
    if len(question) > limits.max_question_chars:
        raise ChatValidationError(f"Вопрос длиннее {limits.max_question_chars} символов")
    history = [m for m in cleaned[:-1] if m.content][-limits.max_history_messages :]
    for m in history:
        if len(m.content) > limits.max_history_message_chars:
            raise ChatValidationError("Слишком длинное сообщение в истории диалога")
    # История начинается с вопроса пользователя: так её ожидает шаблон модели.
    while history and history[0].role != "user":
        history.pop(0)
    return [{"role": m.role, "content": m.content} for m in [*history, cleaned[-1]]]


def _line(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def _error(code: str, model: str) -> bytes:
    return _line({"type": "error", "code": code, "message": ERROR_MESSAGES[code].format(model=model)})


_END = object()


async def stream_events(
    stream: ChatStream, *, model: str, meta: dict, grounding_sources: list[str]
) -> AsyncIterator[bytes]:
    """События для StreamingResponse. При отмене (клиент закрыл соединение)
    Starlette отменяет этот генератор — finally закрывает соединение с Ollama,
    и модель прекращает генерацию."""
    if not _GENERATION_LOCK.acquire(blocking=False):
        yield _error("busy", model)
        return
    iterator = iter(stream)
    answer: list[str] = []
    try:
        yield _line({"type": "meta", "model": model, **meta})
        while True:
            try:
                # abandon_on_cancel: отмена не ждёт, пока модель пришлёт
                # следующий кусок (разбор промпта на процессоре — десятки
                # секунд); соединение закрывается в finally сразу.
                event = await to_thread.run_sync(next, iterator, _END, abandon_on_cancel=True)
            except OllamaError as exc:
                code = exc.state if exc.state in ERROR_MESSAGES else "internal_error"
                yield _error(code, model)
                return
            except Exception:  # noqa: BLE001 — пользователю без технических подробностей
                yield _error("internal_error", model)
                return
            if event is _END:
                yield _error("stream_interrupted", model)
                return
            if isinstance(event, Delta):
                answer.append(event.text)
                yield _line({"type": "delta", "text": event.text})
            elif isinstance(event, Finished):
                grounding = check_numbers("".join(answer), grounding_sources)
                yield _line(
                    {
                        "type": "done",
                        "finish_reason": event.finish_reason,
                        "truncated": event.finish_reason != "stop",
                        "grounding": {"checked": grounding.checked, "unverified": grounding.unverified},
                        "usage": {"prompt_tokens": event.prompt_tokens, "output_tokens": event.output_tokens},
                    }
                )
                return
    finally:
        # Сначала рвём соединение (Ollama перестаёт генерировать), потом
        # отпускаем блокировку. Экранировано от отмены, чтобы выполнилось всегда.
        with anyio.CancelScope(shield=True):
            stream.close()
            _GENERATION_LOCK.release()
