"""API schemas of the flow engine."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.shared.i18n import I18nMap


class _CamelModel(BaseModel):
    """camelCase aliases in JSON; fields populatable by name."""

    model_config = ConfigDict(populate_by_name=True)


class TransitionOut(_CamelModel):
    """A transition available to the current principal (guard satisfied)."""

    id: UUID
    from_state_id: UUID = Field(alias="fromStateId")
    to_state_id: UUID = Field(alias="toStateId")
    label: I18nMap
    # Optional color for the decision button.
    color: str | None = None
    # "Requires action": counts as an open task in the tasks tab.
    requires_action: bool = Field(default=True, alias="requiresAction")


class TransitionRequest(_CamelModel):
    """``POST /applications/{id}/transition`` — fire a transition."""

    transition_id: UUID = Field(alias="transitionId")
    note: str | None = None


class ForceStatusRequest(_CamelModel):
    """``POST /applications/{id}/force-status`` — force a status directly.

    The privileged ``application.force_status`` override; ``note`` (the reason) is
    mandatory since the change bypasses the flow and is audited."""

    state_id: UUID = Field(alias="stateId")
    note: str = Field(min_length=1)


class TransitionResult(_CamelModel):
    """Result of a successful transition (200)."""

    new_state_id: UUID = Field(alias="newStateId")
    status_event_id: UUID = Field(alias="statusEventId")
    dispatched_actions: list[str] = Field(
        default_factory=list, alias="dispatchedActions"
    )
