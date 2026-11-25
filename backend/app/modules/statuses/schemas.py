"""Schemas of the status lists (F/administration/admin/003035)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.shared.i18n import I18nMap
from app.shared.schemas import FrozenCamelModel, FrozenStrictCamelModel

StatusList = Literal["order", "event"]
StatusPhase = Literal["open", "done", "void"]
StatusTone = Literal["neutral", "accent", "warn", "error", "muted"]
StatusDate = Literal["orderedOn", "deliveredOn"]

#: The most statuses of one list.
MAX_STATUSES = 30


class StatusIn(FrozenStrictCamelModel, frozen=True):
    """One status of a list as the admin sends it."""

    key: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    name: I18nMap
    tone: StatusTone = "neutral"
    phase: StatusPhase
    start: bool = False
    sets_date: StatusDate | None = Field(default=None, alias="setsDate")


class StatusListSet(FrozenStrictCamelModel, frozen=True):
    """The whole list in its order, and the replacement of each removed key in use."""

    statuses: tuple[StatusIn, ...] = Field(min_length=3, max_length=MAX_STATUSES)
    replacements: dict[str, str] = Field(default_factory=dict)


class StatusOut(FrozenCamelModel, frozen=True):
    """One status of a list."""

    key: str
    name: I18nMap
    tone: StatusTone
    phase: StatusPhase
    start: bool
    sets_date: StatusDate | None = Field(default=None, alias="setsDate")
    #: How many elements have the status: the editor asks for a replacement on a delete.
    used: int = 0


class StatusListOut(FrozenCamelModel, frozen=True):
    """A status list in its order."""

    kind: StatusList
    statuses: tuple[StatusOut, ...] = ()
