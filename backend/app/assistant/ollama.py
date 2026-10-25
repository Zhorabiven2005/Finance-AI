"""Проверка доступности локального сервера Ollama и выбранной модели.

Сервер считается доступным, только если он ответил корректным JSON на
GET /api/version и GET /api/tags. Открытого порта недостаточно: на 11434 может
слушать что угодно.

Сеть — только стандартная библиотека (urllib), без новых зависимостей, и
только к локальному адресу (проверяется в app.assistant.locality):
  * системные прокси игнорируются — запрос не уйдёт через прокси наружу;
  * перенаправления не выполняются — сервер не может «переслать» запрос
    на другой хост;
  * размер ответа ограничен.
Финансовые данные в этих запросах не передаются. Ответы и ошибки в лог не
пишутся.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from app.assistant.locality import is_cloud_model_name, normalize_local_url

MAX_RESPONSE_BYTES = 1_000_000

AssistantState = Literal[
    "ready",
    "disabled",
    "server_unreachable",
    "server_timeout",
    "server_bad_response",
    "model_not_found",
    "model_not_local",
]


class OllamaError(Exception):
    """Сервер недоступен или ответил не так, как ответил бы Ollama."""

    def __init__(self, state: AssistantState, detail: str) -> None:
        super().__init__(detail)
        self.state = state


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None  # не следовать перенаправлениям: ответ 3xx = ошибка


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


@dataclass(frozen=True)
class ModelInfo:
    name: str
    size_bytes: int | None
    parameter_size: str | None
    quantization: str | None
    remote: bool


@dataclass(frozen=True)
class OllamaStatus:
    state: AssistantState
    server_reachable: bool
    server_version: str | None = None
    model: ModelInfo | None = None
    detail: str | None = None
    models_found: int = 0

    @property
    def ready(self) -> bool:
        return self.state == "ready"


class OllamaClient:
    """Проверки «только чтение» против локального сервера Ollama."""

    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = normalize_local_url(base_url)
        self.timeout = timeout_seconds

    def _get_json(self, path: str) -> Any:
        req = urllib.request.Request(self.base_url + path, method="GET", headers={"Accept": "application/json"})
        try:
            with _OPENER.open(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    raise OllamaError("server_bad_response", f"HTTP {resp.status} на {path}")
                raw = resp.read(MAX_RESPONSE_BYTES + 1)
        except OllamaError:
            raise
        except urllib.error.HTTPError as exc:
            raise OllamaError("server_bad_response", f"HTTP {exc.code} на {path}") from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise OllamaError("server_timeout", f"нет ответа за {self.timeout} с") from None
            raise OllamaError("server_unreachable", "сервер не отвечает") from None
        except (TimeoutError, socket.timeout):
            raise OllamaError("server_timeout", f"нет ответа за {self.timeout} с") from None
        except (ConnectionError, OSError):
            raise OllamaError("server_unreachable", "соединение прервано") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise OllamaError("server_bad_response", f"слишком большой ответ на {path}")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise OllamaError("server_bad_response", f"ответ на {path} — не JSON") from None

    def _probe_tcp(self) -> None:
        """Отдельная проверка подключения. На Windows отказ в подключении к
        закрытому локальному порту приходит только через ~2 с повторных
        попыток, и без этой проверки «Ollama не запущен» выглядел бы как
        «Ollama не ответил вовремя». Доступность по-прежнему подтверждается
        только корректными JSON-ответами ниже — открытого порта мало."""
        parts = urlsplit(self.base_url)
        try:
            with socket.create_connection((parts.hostname, parts.port or 80), timeout=self.timeout):
                pass
        except OSError:
            raise OllamaError("server_unreachable", "сервер не принимает подключения") from None

    def server_version(self) -> str:
        data = self._get_json("/api/version")
        version = data.get("version") if isinstance(data, dict) else None
        if not isinstance(version, str) or not version.strip():
            raise OllamaError("server_bad_response", "в ответе /api/version нет версии")
        return version

    def list_models(self) -> list[ModelInfo]:
        data = self._get_json("/api/tags")
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list):
            raise OllamaError("server_bad_response", "в ответе /api/tags нет списка моделей")
        out: list[ModelInfo] = []
        for m in models:
            if not isinstance(m, dict) or not isinstance(m.get("name"), str):
                raise OllamaError("server_bad_response", "некорректная запись модели в /api/tags")
            details = m.get("details") if isinstance(m.get("details"), dict) else {}
            size = m.get("size")
            out.append(
                ModelInfo(
                    name=m["name"],
                    size_bytes=size if isinstance(size, int) and not isinstance(size, bool) else None,
                    parameter_size=details.get("parameter_size") if isinstance(details.get("parameter_size"), str) else None,
                    quantization=details.get("quantization_level") if isinstance(details.get("quantization_level"), str) else None,
                    # Облачные модели Ollama помечены remote_host/remote_model
                    # или суффиксом cloud: они работают не на этом компьютере.
                    remote=bool(m.get("remote_host") or m.get("remote_model")) or is_cloud_model_name(m["name"]),
                )
            )
        return out

    def check(self, model_name: str) -> OllamaStatus:
        try:
            self._probe_tcp()
            version = self.server_version()
            models = self.list_models()
        except OllamaError as exc:
            return OllamaStatus(state=exc.state, server_reachable=False, detail=str(exc))
        found = find_model(models, model_name)
        if found is None:
            return OllamaStatus(
                state="model_not_found", server_reachable=True, server_version=version, models_found=len(models)
            )
        if found.remote:
            return OllamaStatus(
                state="model_not_local", server_reachable=True, server_version=version, model=found, models_found=len(models)
            )
        return OllamaStatus(state="ready", server_reachable=True, server_version=version, model=found, models_found=len(models))


def find_model(models: list[ModelInfo], wanted: str) -> ModelInfo | None:
    """Точное совпадение имени; имя без тега совпадает с ':latest' (как в Ollama)."""
    candidates = {wanted} if ":" in wanted else {wanted, f"{wanted}:latest"}
    for m in models:
        if m.name in candidates:
            return m
    return None
