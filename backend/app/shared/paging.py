"""Uniform offset paging.

`PageParams` holds the query defaults. `Page[T]` wraps the response.
"""

from __future__ import annotations

from pydantic import Field

from app.shared.schemas import FrozenModel

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class PageParams(FrozenModel, frozen=True):
    """Limit and offset of a paged list."""

    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)
    offset: int = Field(default=0, ge=0)


class Page[T](FrozenModel, frozen=True):
    """One page of a list, with the total count."""

    items: list[T]
    total: int
    limit: int
    offset: int
