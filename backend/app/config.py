"""Конфигурация приложения.

Значения читаются из backend/.env. Секреты (ключ AI-провайдера) живут только
здесь и никогда не покидают backend.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # --- приложение ---------------------------------------------------
    app_name: str = "Finance AI"
    app_version: str = "0.1.0"
    debug: bool = True
    host: str = "127.0.0.1"
    port: int = 8000

    # --- база данных --------------------------------------------------
    # Относительный путь разрешается относительно backend/, чтобы база не
    # зависела от текущего рабочего каталога при запуске.
    database_path: Path = Path("data/finance.db")

    # --- деньги -------------------------------------------------------
    base_currency: str = "RUB"

    # --- уведомления (Stage 2E) ---------------------------------------
    # Интервал периодической проверки внутри backend; 0 — только при старте
    # и вручную.
    notifications_check_interval_minutes: int = Field(default=60, ge=0, le=24 * 60)

    # --- AI: устаревшая заготовка этапа 0 ------------------------------
    # Облачный провайдер не используется и не поддерживается: помощник
    # работает только с локальной моделью (настройки assistant_* ниже).
    # Поля оставлены, чтобы не ломать существующий backend/.env и /health.
    ai_provider: str = "anthropic"
    ai_model: str = "claude-sonnet-5"
    ai_enabled: bool = False
    anthropic_api_key: str | None = Field(default=None, repr=False)

    # --- локальный AI-помощник (Stage 3) ----------------------------------
    # Только локальный сервер Ollama: адрес обязан быть loopback (127.0.0.0/8,
    # ::1, localhost), иначе финансовые данные могли бы уйти с компьютера.
    # Ключей и облачных провайдеров нет.
    assistant_enabled: bool = True
    assistant_ollama_url: str = "http://127.0.0.1:11434"
    assistant_model: str = "qwen3.5:4b-q4_K_M"
    assistant_status_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    # Бюджет текстовой сводки для промпта (оценка: ~3 символа на токен).
    assistant_digest_token_budget: int = Field(default=2500, ge=500, le=16000)
    # --- чат (Stage 3B) ---
    assistant_max_question_chars: int = Field(default=1000, ge=50, le=8000)
    assistant_max_history_messages: int = Field(default=8, ge=1, le=40)
    assistant_max_history_message_chars: int = Field(default=6000, ge=100, le=20000)
    assistant_max_output_tokens: int = Field(default=700, ge=50, le=4000)
    assistant_max_output_chars: int = Field(default=6000, ge=200, le=40000)
    assistant_context_window_tokens: int = Field(default=8192, ge=2048, le=131072)
    # Ожидание очередного куска ответа (включая загрузку модели и разбор промпта)
    # и общий предел на один ответ.
    assistant_chunk_timeout_seconds: float = Field(default=120.0, gt=0, le=600)
    assistant_total_timeout_seconds: float = Field(default=300.0, gt=0, le=1800)

    # --- CORS ---------------------------------------------------------
    # Хранится строкой: pydantic-settings пытается разобрать list как JSON,
    # поэтому список собирается в свойстве cors_origins.
    cors_origins_raw: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="CORS_ORIGINS",
    )

    @field_validator("base_currency")
    @classmethod
    def _validate_currency(cls, v: str) -> str:
        from app.engine.money import get_currency

        return get_currency(v).code

    @field_validator("assistant_ollama_url")
    @classmethod
    def _validate_ollama_url(cls, v: str) -> str:
        from app.assistant.locality import normalize_local_url

        return normalize_local_url(v)

    @field_validator("assistant_model")
    @classmethod
    def _validate_assistant_model(cls, v: str) -> str:
        from app.assistant.locality import validate_local_model_name

        return validate_local_model_name(v)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]

    @property
    def db_file(self) -> Path:
        path = self.database_path
        return path if path.is_absolute() else (BACKEND_DIR / path).resolve()

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_file}"

    @property
    def ai_configured(self) -> bool:
        return self.ai_enabled and bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
