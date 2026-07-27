"""API schemas for the application-types module.

`name` is the i18n label resolved for `lang`. The frontend consumes a ready
string, not the raw `*_i18n` map.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.shared.i18n import DEFAULT_LANG, Lang
from app.shared.paging import PageParams


class _CamelModel(BaseModel):
    """Base model that uses camelCase aliases in JSON and also accepts field names."""

    model_config = ConfigDict(populate_by_name=True)


class ApplicationTypeListQuery(PageParams):
    """Query parameters of the list route: paging and `lang`.

    `extra="forbid"` rejects an unknown query parameter with 422 instead of a
    silent ignore. The cap on `offset` is the int4 maximum, so the DB OFFSET
    cannot overflow into a 500.
    """

    model_config = ConfigDict(extra="forbid")

    # The int4 maximum is an overflow guard, not a business page limit.
    offset: int = Field(default=0, ge=0, le=2_147_483_647)
    # The Lang enum rejects an invalid value such as `lang=null` with 422 instead of ignoring it.
    lang: Lang = DEFAULT_LANG


class ApplicationTypeListItem(_CamelModel):
    """One application type in the list.

    `key` and `gremiumId` are admin-only. They stay `null` without the permission.
    """

    id: UUID
    name: str
    has_budget: bool = Field(alias="hasBudget")
    # active means that the type accepts a submission because an active form version exists.
    active: bool
    active_form_version_id: UUID | None = Field(default=None, alias="activeFormVersionId")
    key: str | None = None
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
