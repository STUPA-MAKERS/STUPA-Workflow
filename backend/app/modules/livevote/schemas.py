"""API-Schemata des Live-Vote/Meeting-Moduls (T-16, api.md §4)."""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime as _datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MeetingStatus = Literal["planned", "live", "closed"]


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; Felder per Name befüllbar."""

    model_config = ConfigDict(populate_by_name=True)


class MeetingCreate(_CamelModel):
    """``POST /api/meetings`` — Sitzung anlegen (Status ``planned``)."""

    gremium_id: UUID = Field(alias="gremiumId")
    title: str = Field(min_length=1)
    date: _date | None = None


class MeetingPatch(_CamelModel):
    """``PATCH /api/meetings/{id}`` — Sitzungs-Steuerung (Beamer/Live).

    Mindestens ein Feld muss gesetzt sein; jede Änderung publiziert ``meeting_state``.
    """

    active_application_id: UUID | None = Field(default=None, alias="activeApplicationId")
    status: MeetingStatus | None = None
    date: _date | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> MeetingPatch:
        # ``date`` zählt mit: geplante Sitzungen lassen sich so vorab terminieren.
        if (
            self.status is None
            and self.active_application_id is None
            and "date" not in self.model_fields_set
        ):
            raise ValueError(
                "at least one of 'status', 'activeApplicationId' or 'date' required"
            )
        return self


class MeetingOut(_CamelModel):
    """Sitzungs-State (``GET /api/meetings/{id}``)."""

    id: UUID
    gremium_id: UUID = Field(alias="gremiumId")
    title: str
    date: _date | None = None
    status: MeetingStatus
    active_application_id: UUID | None = Field(default=None, alias="activeApplicationId")
    protocol_id: UUID | None = Field(default=None, alias="protocolId")
    created_at: _datetime = Field(alias="createdAt")
