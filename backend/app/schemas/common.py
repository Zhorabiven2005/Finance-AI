"""Общие DTO."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Базовый DTO. from_attributes позволяет отдавать ORM-объекты напрямую."""

    model_config = ConfigDict(from_attributes=True)


class HealthResponse(ApiModel):
    status: str
    app: str
    version: str
    database: str
    ai_configured: bool


class CurrencyOut(ApiModel):
    code: str
    exponent: int
    symbol: str
    name: str


class AppSettingsOut(ApiModel):
    base_currency: str
    locale: str
    currency: CurrencyOut
