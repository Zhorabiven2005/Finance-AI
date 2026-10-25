"""Гарантии локальности помощника: адрес Ollama и имя модели.

Модуль используется валидаторами app.config, поэтому импортирует только
стандартную библиотеку (иначе получился бы цикл импорта).
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit, urlunsplit

LOCAL_HOSTNAMES = {"localhost"}


def is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    if host.lower() in LOCAL_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def normalize_local_url(raw: str) -> str:
    """http://<loopback>[:port] без пути, параметров и учётных данных.

    Любой другой адрес отклоняется: финансовые данные не должны уходить
    с компьютера пользователя, даже по ошибке в конфигурации."""
    parts = urlsplit(raw.strip())
    if parts.scheme != "http":
        raise ValueError("Адрес Ollama должен начинаться с http:// (локальный сервер)")
    if parts.username or parts.password:
        raise ValueError("Адрес Ollama не должен содержать учётные данные")
    if not is_loopback_host(parts.hostname):
        raise ValueError(
            "Адрес Ollama должен быть локальным: 127.0.0.1, ::1 или localhost"
        )
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError("Адрес Ollama указывается без пути и параметров")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("Некорректный порт в адресе Ollama") from exc
    netloc = f"[{parts.hostname}]" if ":" in (parts.hostname or "") else parts.hostname
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit(("http", netloc, "", "", ""))


def is_cloud_model_name(name: str) -> bool:
    """Модели Ollama с суффиксом cloud выполняются на серверах Ollama, а не
    на компьютере пользователя."""
    lowered = name.lower()
    return lowered.endswith(":cloud") or lowered.endswith("-cloud")


def validate_local_model_name(raw: str) -> str:
    name = raw.strip()
    if not name:
        raise ValueError("Не указана модель помощника")
    if any(ch.isspace() for ch in name) or "://" in name:
        raise ValueError("Некорректное имя модели")
    if is_cloud_model_name(name):
        raise ValueError("Облачные модели Ollama не поддерживаются: нужна локальная модель")
    return name
