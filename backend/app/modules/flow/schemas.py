"""API schemas of the flow engine."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.shared.i18n import I18nMap


class _CamelModel(BaseModel):
    """Use camelCase aliases in JSON. The caller may also populate the fields by name."""

    model_config = ConfigDict(populate_by_name=True)


class TransitionOut(_CamelModel):
    """A transition available to the current principal (guard satisfied)."""

    id: UUID
    from_state_id: UUID = Field(alias="fromStateId")
    to_state_id: UUID = Field(alias="toStateId")
    label: I18nMap
    # Optional color for the decision button.
    color: str | None = None
    # Requires action: the transition counts as an open task in the tasks tab.
    requires_action: bool = Field(default=True, alias="requiresAction")
    # The transition carries an `addToNextSession` action. The UI then offers the
    # "put on the agenda" dialog with the planned meetings of `agendaGremiumId`.
    adds_to_agenda: bool = Field(default=False, alias="addsToAgenda")
    agenda_gremium_id: UUID | None = Field(default=None, alias="agendaGremiumId")


class TransitionRequest(_CamelModel):
    """`POST /applications/{id}/transition` — fire a transition.

    `meetingId` picks the meeting for the `addToNextSession` action of the
    transition. The engine then adds the agenda item in the same transaction as the
    state change and skips the action after the commit. Without `meetingId` the
    action picks the next planned meeting after the commit. `nonPublic` marks the new
    agenda item as not public.
    """

    transition_id: UUID = Field(alias="transitionId")
    note: str | None = None
    meeting_id: UUID | None = Field(default=None, alias="meetingId")
    non_public: bool = Field(default=False, alias="nonPublic")


class ForceStatusRequest(_CamelModel):
    """`POST /applications/{id}/force-status` — force a status directly.

    This is the privileged `application.force_status` override. The `note` gives the
    reason. It is mandatory because the change bypasses the flow and gets audited.
    """

    state_id: UUID = Field(alias="stateId")
    note: str = Field(min_length=1)


class TransitionResult(_CamelModel):
    """Result of a successful transition (200)."""

    new_state_id: UUID = Field(alias="newStateId")
    status_event_id: UUID = Field(alias="statusEventId")
    dispatched_actions: list[str] = Field(
        default_factory=list, alias="dispatchedActions"
    )
