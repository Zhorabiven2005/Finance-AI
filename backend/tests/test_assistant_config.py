"""Настройки локального помощника: только loopback и только локальные модели."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings, settings


def make(**over):
    return Settings(_env_file=None, **over)


def test_defaults_are_local_and_need_no_api_key():
    s = make()
    assert s.assistant_enabled is True
    assert s.assistant_ollama_url == "http://127.0.0.1:11434"
    assert s.assistant_model == "qwen3.5:4b-q4_K_M"
    assert s.anthropic_api_key is None  # ключ облачного провайдера не нужен


def test_working_env_file_does_not_override_assistant_model():
    # В рабочем backend/.env остались AI_PROVIDER/AI_MODEL от заготовки этапа 0;
    # они не влияют на помощника.
    assert settings.assistant_model == "qwen3.5:4b-q4_K_M"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
        ("http://localhost:11434/", "http://localhost:11434"),
        (" http://127.0.0.2:8080 ", "http://127.0.0.2:8080"),
        ("http://[::1]:11434", "http://[::1]:11434"),
    ],
)
def test_loopback_urls_accepted(raw, expected):
    assert make(assistant_ollama_url=raw).assistant_ollama_url == expected


@pytest.mark.parametrize(
    "raw",
    [
        "https://127.0.0.1:11434",
        "http://192.168.1.10:11434",
        "http://10.0.0.5:11434",
        "http://example.com:11434",
        "http://ollama.com",
        "http://user:secret@127.0.0.1:11434",
        "http://127.0.0.1:11434/api",
        "http://127.0.0.1:11434?x=1",
        "http://127.0.0.1:99999",
        "ftp://127.0.0.1",
        "127.0.0.1:11434",
    ],
)
def test_non_local_urls_rejected(raw):
    with pytest.raises(ValidationError):
        make(assistant_ollama_url=raw)


@pytest.mark.parametrize("name", ["", "   ", "gpt-oss:120b-cloud", "qwen3.5:cloud", "two words", "https://evil/model"])
def test_cloud_or_invalid_model_names_rejected(name):
    with pytest.raises(ValidationError):
        make(assistant_model=name)


def test_model_can_be_changed():
    assert make(assistant_model="gemma3:4b").assistant_model == "gemma3:4b"


def test_secrets_not_in_repr():
    s = make(anthropic_api_key="sk-test-secret")
    assert "sk-test-secret" not in repr(s)
