"""DTO для денежных сумм.

Совпадает по форме с MoneyAmount на фронтенде (frontend/src/lib/money.ts):
{minor, currency}. Frontend форматирует и парсит суммы сам, backend отдаёт
и принимает только целые минорные единицы — float нигде не участвует.
"""

from __future__ import annotations

from app.schemas.common import ApiModel


class MoneyOut(ApiModel):
    minor: int
    currency: str
