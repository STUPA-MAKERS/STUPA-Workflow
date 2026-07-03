"""API schemas for the application-types module.

``name`` is the i18n label resolved for ``lang`` — the frontend consumes a
ready string, not the raw ``*_i18n`` map.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.shared.i18n import DEFAULT_LANG, Lang
from app.shared.paging import PageParams


class _CamelModel(BaseModel):
    """camelCase aliases in JSON; fields populatable by name."""

    model_config = ConfigDict(populate_by_name=True)


class ApplicationTypeListQuery(PageParams):
    """List query params: paging plus ``lang``.

    ``extra="forbid"`` rejects unknown query params with 422 instead of silently
    ignoring them; ``offset`` is capped at int4 max so the DB OFFSET cannot
    overflow into a 500.
    """

    model_config = ConfigDict(extra="forbid")

    # int4 max: overflow guard only, not a business page limit.
    offset: int = Field(default=0, ge=0, le=2_147_483_647)
    # Lang enum: invalid values (e.g. `lang=null`) fail with 422 instead of being ignored.
    lang: Lang = DEFAULT_LANG


class ApplicationTypeListItem(_CamelModel):
    """One application type in the list.

    ``key`` and ``gremiumId`` are admin-only and ``null`` without permission.
    """

    id: UUID
    name: str
    has_budget: bool = Field(alias="hasBudget")
    # active = offerable for submission (an active form version exists).
    active: bool
    active_form_version_id: UUID | None = Field(default=None, alias="activeFormVersionId")
    # Admin-only fields (populated only with permission).
    key: str | None = None
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
