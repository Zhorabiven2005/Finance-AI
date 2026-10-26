"""Потоковая генерация ответа локальной моделью Ollama (Stage 3B).

Формат Ollama /api/chat при stream=true — NDJSON: по JSON-объекту на строку,
{"message": {"role", "content"[, "thinking"]}, "done": false}, последний —
{"done": true, "done_reason": "stop" | "length", ...}. Проверено на
qwen3.5:4b-q4_K_M (Ollama 0.40.8): при think=false поля thinking нет, при
think=true рассуждения приходят отдельным полем message.thinking.

Рассуждения не доходят до пользователя тремя слоями:
  1. в запросе think=false (поддерживаемый параметр Ollama);
  2. поле message.thinking никогда не пересылается;
  3. ThinkFilter вырезает <think>…</think> из текста — на случай модели,
     которая пишет рассуждения прямо в content, в том числе с разрывом тега
     между кусками потока.

У модели нет инструментов: в запросе нет tools/format, только сообщения.
Сеть — та же защита, что и у проверки статуса: только loopback, без прокси и
перенаправлений. Сообщения и ответы нигде не сохраняются и не логируются.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from app.assistant.ollama import _OPENER, OllamaClient, OllamaError

MAX_LINE_BYTES = 1_000_000

THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"

FinishReason = Literal["stop", "length", "output_limit"]


class ThinkFilter:
    """Вырезает <think>…</think> из потока текста, в том числе когда тег
    разорван между кусками. Незакрытый блок рассуждений отбрасывается целиком."""

    def __init__(self) -> None:
        self._buf = ""
        self._inside = False
        self.removed_chars = 0

    @staticmethod
    def _partial_suffix(text: str, tag: str) -> int:
        """Длина конца text, который может оказаться началом tag."""
        for n in range(min(len(text), len(tag) - 1), 0, -1):
            if tag.startswith(text[-n:]):
                return n
        return 0

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        out: list[str] = []
        while True:
            if self._inside:
                end = self._buf.find(THINK_CLOSE)
                if end == -1:
                    keep = self._partial_suffix(self._buf, THINK_CLOSE)
                    self.removed_chars += len(self._buf) - keep
                    self._buf = self._buf[len(self._buf) - keep :]
                    break
                self.removed_chars += end + len(THINK_CLOSE)
                self._buf = self._buf[end + len(THINK_CLOSE) :]
                self._inside = False
            else:
                start = self._buf.find(THINK_OPEN)
                if start == -1:
                    keep = self._partial_suffix(self._buf, THINK_OPEN)
                    out.append(self._buf[: len(self._buf) - keep])
                    self._buf = self._buf[len(self._buf) - keep :]
                    break
                out.append(self._buf[:start])
                self._buf = self._buf[start + len(THINK_OPEN) :]
                self._inside = True
        return "".join(out)

    def flush(self) -> str:
        rest = "" if self._inside else self._buf
        if self._inside:
            self.removed_chars += len(self._buf)
        self._buf = ""
        return rest


@dataclass(frozen=True)
class Delta:
    text: str


@dataclass(frozen=True)
class Finished:
    finish_reason: FinishReason
    prompt_tokens: int | None
    output_tokens: int | None
    thinking_dropped: bool


Event = Delta | Finished


class ChatStream:
    """Поток ответа одной генерации. close() рвёт соединение с Ollama — сервер
    прекращает генерацию (так работает отмена запроса пользователем)."""

    def __init__(
        self,
        client: OllamaClient,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_output_tokens: int,
        context_window_tokens: int,
        max_output_chars: int,
        chunk_timeout: float,
        total_timeout: float,
    ) -> None:
        self._client = client
        self._body = {
            "model": model,
            "stream": True,
            "think": False,
            "messages": messages,
            "options": {"temperature": 0.2, "num_ctx": context_window_tokens, "num_predict": max_output_tokens},
        }
        self._max_output_chars = max_output_chars
        self._chunk_timeout = chunk_timeout
        self._total_timeout = total_timeout
        self._resp = None
        self._closed = False

    @property
    def request_body(self) -> dict:
        return self._body

    def close(self) -> None:
        self._closed = True
        resp, self._resp = self._resp, None
        if resp is not None:
            try:
                resp.close()
            except Exception:  # noqa: BLE001 — соединение уже могло оборваться
                pass

    def _open(self):
        self._client.probe()  # «Ollama не запущен» отличается от «таймаута»
        req = urllib.request.Request(
            self._client.base_url + "/api/chat",
            data=json.dumps(self._body).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/x-ndjson"},
        )
        try:
            return _OPENER.open(req, timeout=self._chunk_timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise OllamaError("model_not_found", "модель не найдена") from None
            raise OllamaError("server_bad_response", f"HTTP {exc.code}") from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise OllamaError("server_timeout", "нет ответа") from None
            raise OllamaError("server_unreachable", "сервер не отвечает") from None
        except (TimeoutError, socket.timeout):
            raise OllamaError("server_timeout", "нет ответа") from None
        except OSError:
            raise OllamaError("server_unreachable", "соединение прервано") from None

    def __iter__(self) -> Iterator[Event]:
        started = time.monotonic()
        self._resp = self._open()
        think = ThinkFilter()
        emitted = 0
        thinking_seen = False
        try:
            while True:
                if self._closed:
                    return
                if time.monotonic() - started > self._total_timeout:
                    raise OllamaError("generation_timeout", "превышено общее время ответа")
                try:
                    line = self._resp.readline(MAX_LINE_BYTES + 1) if self._resp else b""
                except (TimeoutError, socket.timeout):
                    raise OllamaError("generation_timeout", "модель перестала отвечать") from None
                except (OSError, ValueError, AttributeError):
                    if self._closed:
                        return
                    raise OllamaError("stream_interrupted", "поток ответа оборвался") from None
                if not line:
                    if self._closed:
                        return
                    raise OllamaError("stream_interrupted", "поток закончился без завершения")
                if len(line) > MAX_LINE_BYTES:
                    raise OllamaError("server_bad_response", "слишком длинная строка потока")
                if not line.strip():
                    continue
                try:
                    event = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise OllamaError("server_bad_response", "строка потока — не JSON") from None
                if not isinstance(event, dict):
                    raise OllamaError("server_bad_response", "строка потока — не объект")
                if "error" in event:
                    raise OllamaError("generation_error", "модель вернула ошибку")
                message = event.get("message") if isinstance(event.get("message"), dict) else {}
                if message.get("thinking"):
                    thinking_seen = True  # отдельное поле рассуждений — не пересылается
                content = message.get("content")
                if isinstance(content, str) and content:
                    text = think.feed(content)
                    if text:
                        if emitted + len(text) > self._max_output_chars:
                            text = text[: self._max_output_chars - emitted]
                            if text:
                                yield Delta(text)
                            yield Finished("output_limit", event.get("prompt_eval_count"), event.get("eval_count"), thinking_seen or think.removed_chars > 0)
                            return
                        emitted += len(text)
                        yield Delta(text)
                if event.get("done") is True:
                    tail = think.flush()
                    if tail:
                        tail = tail[: max(0, self._max_output_chars - emitted)]
                        if tail:
                            yield Delta(tail)
                    reason = "length" if event.get("done_reason") == "length" else "stop"
                    yield Finished(
                        reason,
                        event.get("prompt_eval_count") if isinstance(event.get("prompt_eval_count"), int) else None,
                        event.get("eval_count") if isinstance(event.get("eval_count"), int) else None,
                        thinking_seen or think.removed_chars > 0,
                    )
                    return
        finally:
            self.close()
