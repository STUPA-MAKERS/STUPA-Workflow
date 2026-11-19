"""API schemas of the flow engine."""

from __future__ import annotations

from typing import Literal, get_args
from uuid import UUID

from pydantic import Field, model_validator

from app.modules.applications.decision import DecisionIn
from app.shared.i18n import I18nMap
from app.shared.schemas import FrozenCamelModel


class TransitionOut(FrozenCamelModel, frozen=True):
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
        requires_amount: The fire must name the approved amount (spec 001610): the
            target is an approved state, the current state is not, and the
            application has an amount. The dialog then shows the amount without the
            switch.
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
    requires_amount: bool = Field(default=False, alias="requiresAmount")


class TransitionRequest(FrozenCamelModel, frozen=True):
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


#: The reasons of a forced status (spec 001650), as keys. The report counts per key.
ForceReason = Literal["outside_decision", "applicant_error", "error_correction", "other"]
FORCE_REASONS: tuple[ForceReason, ...] = get_args(ForceReason)

#: The reason `other` needs a text of at least this many characters after the trim.
MIN_OTHER_NOTE = 10


class ForceStatusRequest(FrozenCamelModel, frozen=True):
    """`POST /applications/{id}/force-status` — force a status directly.

    This is the privileged `application.force_status` override. The `reason` names why
    from a fixed list, because the report of the forced changes counts per reason and
    shows the ways that the flow lacks. The `note` is optional, except for `other`,
    which needs at least 10 characters after the trim.
    """

    state_id: UUID = Field(alias="stateId")
    reason: ForceReason
    note: str | None = None

    @model_validator(mode="after")
    def _note_for_other(self) -> ForceStatusRequest:
        """Refuse `other` without a note of at least 10 characters."""
        text = (self.note or "").strip()
        if self.reason == "other" and len(text) < MIN_OTHER_NOTE:
            raise ValueError(f"the reason 'other' needs a note of {MIN_OTHER_NOTE} characters")
        return self

    @property
    def clean_note(self) -> str | None:
        """Return the trimmed note, or None for an empty one."""
        text = (self.note or "").strip()
        return text or None


class TransitionResult(FrozenCamelModel, frozen=True):
    """Result of a successful transition (200)."""

    new_state_id: UUID = Field(alias="newStateId")
    status_event_id: UUID = Field(alias="statusEventId")
    dispatched_actions: list[str] = Field(default_factory=list, alias="dispatchedActions")
