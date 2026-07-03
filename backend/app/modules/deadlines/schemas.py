"""API schemas for the deadline-policy registry.

A policy is either ``absolute`` (fixed date) or relative
(``relative_submitted``/``relative_changed`` = application timestamp + days).
The flow references it by ``key``; the server derives concrete deadlines.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.shared.i18n import I18nMap

DeadlineKind = Literal["absolute", "relative_submitted", "relative_changed"]


class _CamelModel(BaseModel):
    """camelCase aliases in JSON; fields also settable by name."""

    model_config = ConfigDict(populate_by_name=True)


class DeadlinePolicyCreate(_CamelModel):
    key: str
    label: I18nMap
    kind: DeadlineKind
    # tz-aware only: naive values would be interpreted in the DB session TZ and
    # could fire hours off. ``AwareDatetime`` rejects naive input with 422.
    absolute_at: AwareDatetime | None = Field(default=None, alias="absoluteAt")
    offset_days: int | None = Field(default=None, alias="offsetDays")


class DeadlinePolicyUpdate(_CamelModel):
    """Partial update; set fields are applied (``key`` is immutable)."""

    label: I18nMap | None = None
    kind: DeadlineKind | None = None
    absolute_at: AwareDatetime | None = Field(default=None, alias="absoluteAt")
    offset_days: int | None = Field(default=None, alias="offsetDays")


class DeadlinePolicyOut(_CamelModel):
    id: UUID
    key: str
    label: I18nMap
    kind: DeadlineKind
    absolute_at: datetime | None = Field(default=None, alias="absoluteAt")
    offset_days: int | None = Field(default=None, alias="offsetDays")
