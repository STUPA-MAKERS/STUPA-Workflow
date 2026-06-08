"""API-Schemata der Flow-Engine (T-14, api.md »flow«)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.shared.i18n import I18nMap


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; Felder per Name befüllbar."""

    model_config = ConfigDict(populate_by_name=True)


class TransitionOut(_CamelModel):
    """Ein für den aktuellen Principal **verfügbarer** Übergang (Guard erfüllt)."""

    id: UUID
    from_state_id: UUID = Field(alias="fromStateId")
    to_state_id: UUID = Field(alias="toStateId")
    label: I18nMap


class TransitionRequest(_CamelModel):
    """``POST /applications/{id}/transition`` — Übergang feuern (api.md §5)."""

    transition_id: UUID = Field(alias="transitionId")
    note: str | None = None


class ApprovalRequest(_CamelModel):
    """``POST /applications/{id}/approval`` — Approval-State entscheiden (#28)."""

    decision: Literal["accept", "reject"]


class TransitionResult(_CamelModel):
    """Ergebnis eines erfolgreichen Übergangs (200)."""

    new_state_id: UUID = Field(alias="newStateId")
    status_event_id: UUID = Field(alias="statusEventId")
    dispatched_actions: list[str] = Field(
        default_factory=list, alias="dispatchedActions"
    )
