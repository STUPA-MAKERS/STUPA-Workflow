"""Einheitliches Offset-Paging (overview §5, api.md).

`PageParams` = Query-Defaults; `Page[T]` = Antwort-Hülle. Cursor-Paging später
modulweise ergänzbar.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class PageParams(BaseModel):
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    offset: int = Field(default=0, ge=0)


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
