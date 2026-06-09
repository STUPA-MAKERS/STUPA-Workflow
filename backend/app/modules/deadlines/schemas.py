"""API-Schemata der Deadline-Policy-Registry (benannte Fristen).

Eine Policy ist entweder ``absolute`` (fixes Datum, pro Semester pflegbar) oder
relativ (``relative_submitted``/``relative_changed`` = Antrags-Zeitpunkt + Tage).
Der Flow referenziert sie über ``key``; konkrete Fristen löst der Server daraus ab.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.shared.i18n import I18nMap

DeadlineKind = Literal["absolute", "relative_submitted", "relative_changed"]


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; Felder per Name befüllbar."""

    model_config = ConfigDict(populate_by_name=True)


class DeadlinePolicyCreate(_CamelModel):
    key: str
    label: I18nMap
    kind: DeadlineKind
    absolute_at: datetime | None = Field(default=None, alias="absoluteAt")
    offset_days: int | None = Field(default=None, alias="offsetDays")


class DeadlinePolicyUpdate(_CamelModel):
    """Teil-Update; gesetzte Felder werden übernommen (``key`` ist unveränderlich)."""

    label: I18nMap | None = None
    kind: DeadlineKind | None = None
    absolute_at: datetime | None = Field(default=None, alias="absoluteAt")
    offset_days: int | None = Field(default=None, alias="offsetDays")


class DeadlinePolicyOut(_CamelModel):
    id: UUID
    key: str
    label: I18nMap
    kind: DeadlineKind
    absolute_at: datetime | None = Field(default=None, alias="absoluteAt")
    offset_days: int | None = Field(default=None, alias="offsetDays")
