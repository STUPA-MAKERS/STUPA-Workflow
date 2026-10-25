"""API schemas of the flow engine."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.applications.decision import DecisionIn
from app.shared.i18n import I18nMap


class _CamelModel(BaseModel):
    """Use camelCase aliases in JSON. The caller may also populate the fields by name."""

    model_config = ConfigDict(populate_by_name=True)


class TransitionOut(_CamelModel):
    """A transition available to the current principal (guard satisfied).

    Attributes:
        color: Optional color of the decision button.
        requires_action: The transition counts as an open task in the tasks tab.
        adds_to_agenda: The transition carries an `addToNextSession` action and leads
            into a vote state, so a fire takes a `meetingId`. The UI then offers the
            "put on the agenda" dialog with the planned meetings of `agendaGremiumId`.
            With the action into a normal state the value is `false`: the transition
            fires without a meeting, and the action picks the next planned meeting
            after the commit.
        allows_decision: The target is an accepted state of the top budget of the
            application, so a fire takes a `decision` (approval with deviations). The
            UI then opens the decision dialog.
    """

    id: UUID
    from_state_id: UUID = Field(alias="fromStateId")
    to_state_id: UUID = Field(alias="toStateId")
    label: I18nMap
    color: str | None = None
    requires_action: bool = Field(default=True, alias="requiresAction")
    adds_to_agenda: bool = Field(default=False, alias="addsToAgenda")
    agenda_gremium_id: UUID | None = Field(default=None, alias="agendaGremiumId")
    allows_decision: bool = Field(default=False, alias="allowsDecision")


class TransitionRequest(_CamelModel):
    """`POST /applications/{id}/transition` — fire a transition.

    `meetingId` picks the meeting for the `addToNextSession` action of the
    transition. The engine then adds the agenda item in the same transaction as the
    state change and skips the action after the commit. Without `meetingId` the
    action picks the next planned meeting after the commit. `nonPublic` marks the new
    agenda item as not public. `decision` sets the approved amount and the
    conditions.

    Only a transition into an accepted state of the top budget takes a `decision`. Any other
    transition gives 422 `decision_not_allowed`.
    """

    transition_id: UUID = Field(alias="transitionId")
    note: str | None = None
    meeting_id: UUID | None = Field(default=None, alias="meetingId")
    non_public: bool = Field(default=False, alias="nonPublic")
    decision: DecisionIn | None = None


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
