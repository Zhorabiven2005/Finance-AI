from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.common import ApiModel
from app.schemas.money import MoneyOut


class TransferCreate(ApiModel):
    from_account_id: int
    to_account_id: int
    amount_minor: int = Field(gt=0)
    occurred_at: datetime
    comment: str | None = Field(default=None, max_length=500)


class TransferUpdate(ApiModel):
    amount_minor: int | None = Field(default=None, gt=0)
    occurred_at: datetime | None = None
    comment: str | None = Field(default=None, max_length=500)


class TransferOut(ApiModel):
    id: int
    from_account_id: int
    to_account_id: int
    amount: MoneyOut
    occurred_at: datetime
    comment: str | None
