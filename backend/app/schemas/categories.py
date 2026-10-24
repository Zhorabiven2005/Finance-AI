from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel

CategoryType = Literal["income", "expense"]

# Иконка — ключ из набора Lucide на фронтенде (kebab-case), а не эмодзи.
ICON_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class CategoryCreate(ApiModel):
    name: str = Field(min_length=1, max_length=100)
    type: CategoryType
    icon: str | None = Field(default=None, max_length=50, pattern=ICON_PATTERN)
    parent_id: int | None = None


class CategoryUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    type: CategoryType | None = None
    icon: str | None = Field(default=None, max_length=50, pattern=ICON_PATTERN)
    parent_id: int | None = None
    is_archived: bool | None = None


class CategoryOut(ApiModel):
    id: int
    name: str
    type: str
    icon: str | None
    parent_id: int | None
    is_default: bool
    is_archived: bool
