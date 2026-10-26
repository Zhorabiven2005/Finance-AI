"""Архитектурные гарантии помощника Stage 3A: только чтение и только локально."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
ASSISTANT_SOURCES = sorted((APP / "assistant").glob("*.py"))
API_SOURCE = APP / "api" / "v1" / "assistant.py"

FORBIDDEN = {
    "прямой доступ к SQLite": r"\bsqlite3\b",
    "свой движок или сессия БД": r"\b(SessionLocal|create_engine)\b|from app\.db\.session import",
    "запись через сессию": r"\bdb\.(add|add_all|delete|commit|flush|merge|execute)\(",
    "SQL-запросы": r"\b(select|insert|update|delete)\(",
    "shell и процессы": r"\b(subprocess|os\.system|os\.popen|shutil)\b",
    # Встроенная open(); метод _OPENER.open(...) у HTTP-клиента — не файл.
    "файловая система": r"(?<![.\w])open\(|\.write_text\(|\.write_bytes\(|\bPath\(",
    "сторонние HTTP-клиенты": r"\b(requests|httpx|aiohttp)\b",
    "внешние адреса": r"https?://(?!127\.0\.0\.1|localhost|\[::1\])[\w.-]+",
    "логирование и печать данных": r"\b(logging|logger|print)\b",
    "облачные провайдеры": r"\b(anthropic|openai)\b",
}


def sources():
    assert len(ASSISTANT_SOURCES) >= 4
    return {p.name: p.read_text(encoding="utf-8") for p in ASSISTANT_SOURCES}


def strip_docs(code: str) -> str:
    """Без строк документации и комментариев: проверяется только код."""
    code = re.sub(r'"""[\s\S]*?"""', "", code)
    return re.sub(r"#.*", "", code)


@pytest.mark.parametrize("rule", list(FORBIDDEN))
def test_assistant_package_rules(rule):
    pattern = FORBIDDEN[rule]
    offenders = [name for name, code in sources().items() if re.search(pattern, strip_docs(code))]
    assert offenders == [], f"{rule}: {offenders}"


def test_preview_endpoint_uses_readonly_session_only():
    code = strip_docs(API_SOURCE.read_text(encoding="utf-8"))
    assert "Depends(get_readonly_db)" in code
    assert "Depends(get_db)" not in code
    assert not re.search(FORBIDDEN["запись через сессию"], code)
    assert not re.search(FORBIDDEN["прямой доступ к SQLite"], code)


def test_only_chat_generation_is_called_and_no_model_management():
    # Генерация — только /api/chat и только из модуля generation.py. Управлять
    # моделями (загружать, удалять, создавать) помощник не может.
    all_code = {name: strip_docs(code) for name, code in sources().items()}
    all_code["api/v1/assistant.py"] = strip_docs(API_SOURCE.read_text(encoding="utf-8"))
    for name, code in all_code.items():
        for endpoint in ("/api/generate", "/v1/chat/completions", "/api/pull", "/api/delete", "/api/create", "/api/push", "/api/copy"):
            assert endpoint not in code, (name, endpoint)
        if name != "generation.py":
            assert "/api/chat" not in code, name


def test_model_gets_no_tools():
    code = strip_docs((APP / "assistant" / "generation.py").read_text(encoding="utf-8"))
    assert '"tools"' not in code and "'tools'" not in code
    assert '"think": False' in code


@pytest.mark.parametrize("module", ["app.assistant.ollama", "app.assistant.digest", "app.api.v1.assistant", "app.config"])
def test_module_imports_first_without_cycle(module):
    result = subprocess.run(
        [sys.executable, "-B", "-c", f"import {module}"], cwd=APP.parent, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
