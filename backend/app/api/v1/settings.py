"""Настройки приложения."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import AppSettings
from app.db.models.app_settings import SINGLETON_ID
from app.db.session import get_db
from app.engine.money import REGISTERED_CURRENCIES, get_currency
from app.schemas.common import AppSettingsOut, CurrencyOut

router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=AppSettingsOut)
def read_settings(db: Session = Depends(get_db)) -> AppSettingsOut:
    row = db.get(AppSettings, SINGLETON_ID)
    if row is None:
        # База ещё не инициализирована — отдаём значения из конфигурации.
        from app.config import settings as cfg

        cur = get_currency(cfg.base_currency)
        return AppSettingsOut(
            base_currency=cur.code,
            locale="ru-RU",
            currency=CurrencyOut.model_validate(cur, from_attributes=True),
        )
    cur = get_currency(row.base_currency)
    return AppSettingsOut(
        base_currency=row.base_currency,
        locale=row.locale,
        currency=CurrencyOut.model_validate(cur, from_attributes=True),
    )


@router.get("/currencies", response_model=list[CurrencyOut])
def list_currencies() -> list[CurrencyOut]:
    return [
        CurrencyOut.model_validate(c, from_attributes=True)
        for c in REGISTERED_CURRENCIES.values()
    ]
