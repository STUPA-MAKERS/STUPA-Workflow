"""API schemas for the deadline-policy registry.

A policy is one of three forms. `absolute` is a fixed date. `relative_submitted`
and `relative_changed` add a number of days to an application timestamp.
`recurring` is a rolling window that takes the earliest of `dates` still ahead.
The flow references a policy by `key`. The server derives the concrete
deadlines.

`atTime` and `timezone` anchor the wall clock for every kind. This is optional.
`atTime` is a local `"HH:MM"` time and the result stays DST-correct. If both are
unset, the raw-instant behavior stays.
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
    """Reject a `recurring` policy that carries no date."""
    if kind == "recurring" and not dates:
        raise ValueError("recurring policy requires a non-empty 'dates' list")


class _CamelModel(BaseModel):
    """Base model that uses camelCase aliases in JSON.

    The caller can also set a field by its Python name.
    """

    model_config = ConfigDict(populate_by_name=True)


class _PolicyAnchor(_CamelModel):
    """Wall-clock anchor and rolling-schedule fields shared by create and update."""

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
    # Timezone-aware values only: the database session reads a naive value in
    # its own timezone, and the deadline can then fire hours off.
    # `AwareDatetime` rejects naive input with 422.
    absolute_at: AwareDatetime | None = Field(default=None, alias="absoluteAt")
    offset_days: int | None = Field(default=None, alias="offsetDays")

    @model_validator(mode="after")
    def _check_recurring(self) -> DeadlinePolicyCreate:
        _require_recurring_dates(self.kind, self.dates)
        return self


class DeadlinePolicyUpdate(_PolicyAnchor):
    """Partial update of a policy.

    The server applies the fields that the caller sets. `key` is immutable.
    """

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
