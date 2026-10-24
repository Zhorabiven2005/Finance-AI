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

    # --- AI (используется начиная с этапа 6) --------------------------
    ai_provider: str = "anthropic"
    ai_model: str = "claude-sonnet-5"
    ai_enabled: bool = False
    anthropic_api_key: str | None = Field(default=None, repr=False)

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
