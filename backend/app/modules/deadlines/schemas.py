"""API schemas for the deadline-policy registry.

A policy is ``absolute`` (fixed date), relative
(``relative_submitted``/``relative_changed`` = application timestamp + days) or
``recurring`` (a rolling window: the earliest of ``dates`` still ahead). The flow
references it by ``key``; the server derives concrete deadlines.

``atTime``/``timezone`` optionally anchor the wall-clock (``"HH:MM"`` local time,
DST-correct) for every kind; both unset keeps the raw-instant behaviour.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.shared.i18n import I18nMap

DeadlineKind = Literal[
    "absolute", "relative_submitted", "relative_changed", "recurring"
]

_HHMM_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _check_at_time(value: str | None) -> str | None:
    if value is None:
        return None
    if not _HHMM_RE.match(value):
        raise ValueError('atTime must be "HH:MM" in 00:00–23:59')
    return value


def _check_timezone(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown timezone: {value!r}") from exc
    return value


def _check_dates(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    for raw in value:
        try:
            date.fromisoformat(raw)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"dates must be ISO 'YYYY-MM-DD' strings: {raw!r}") from exc
    return value


def _require_recurring_dates(kind: str | None, dates: list[str] | None) -> None:
    """A ``recurring`` policy is meaningless without at least one date."""
    if kind == "recurring" and not dates:
        raise ValueError("recurring policy requires a non-empty 'dates' list")


class _CamelModel(BaseModel):
    """camelCase aliases in JSON; fields also settable by name."""

    model_config = ConfigDict(populate_by_name=True)


class _PolicyAnchor(_CamelModel):
    """Wall-clock anchor + rolling schedule fields shared by create/update."""

    at_time: str | None = Field(default=None, alias="atTime")
    timezone: str | None = Field(default=None)
    dates: list[str] | None = Field(default=None)

    _v_at_time = field_validator("at_time")(_check_at_time)
    _v_timezone = field_validator("timezone")(_check_timezone)
    _v_dates = field_validator("dates")(_check_dates)


class DeadlinePolicyCreate(_PolicyAnchor):
    key: str
    label: I18nMap
    kind: DeadlineKind
    # tz-aware only: naive values would be interpreted in the DB session TZ and
    # could fire hours off. ``AwareDatetime`` rejects naive input with 422.
    absolute_at: AwareDatetime | None = Field(default=None, alias="absoluteAt")
    offset_days: int | None = Field(default=None, alias="offsetDays")

    @model_validator(mode="after")
    def _check_recurring(self) -> DeadlinePolicyCreate:
        _require_recurring_dates(self.kind, self.dates)
        return self


class DeadlinePolicyUpdate(_PolicyAnchor):
    """Partial update; set fields are applied (``key`` is immutable)."""

    label: I18nMap | None = None
    kind: DeadlineKind | None = None
    absolute_at: AwareDatetime | None = Field(default=None, alias="absoluteAt")
    offset_days: int | None = Field(default=None, alias="offsetDays")

    @model_validator(mode="after")
    def _check_recurring(self) -> DeadlinePolicyUpdate:
        _require_recurring_dates(self.kind, self.dates)
        return self


class DeadlinePolicyOut(_CamelModel):
    id: UUID
    key: str
    label: I18nMap
    kind: DeadlineKind
    absolute_at: datetime | None = Field(default=None, alias="absoluteAt")
    offset_days: int | None = Field(default=None, alias="offsetDays")
    at_time: str | None = Field(default=None, alias="atTime")
    timezone: str | None = Field(default=None)
    dates: list[str] | None = Field(default=None)
