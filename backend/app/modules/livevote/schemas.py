"""API schemas for the live-vote/meeting module."""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime as _datetime
from datetime import time as _time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MeetingStatus = Literal["planned", "live", "closed"]


class _CamelModel(BaseModel):
    """Base model with camelCase aliases in JSON.

    Code can also set the fields by their Python name.
    """

    model_config = ConfigDict(populate_by_name=True)


class MeetingCreate(_CamelModel):
    """``POST /api/meetings`` — create a meeting (status ``planned``)."""

    gremium_id: UUID = Field(alias="gremiumId")
    title: str = Field(min_length=1)
    date: _date
    start_time: _time = Field(alias="startTime")
    # Without an end time the iCal feed assumes a duration of one hour.
    end_time: _time | None = Field(default=None, alias="endTime")
    # The protokollant must be a member of the Gremium.
    protokollant_id: UUID | None = Field(default=None, alias="protokollantId")

    @model_validator(mode="after")
    def _end_after_start(self) -> MeetingCreate:
        if self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("endTime must be after startTime")
        return self


class MeetingPatch(_CamelModel):
    """``PATCH /api/meetings/{id}`` — control or plan a meeting.

    At least one field must be set. Any change publishes ``meeting_state``.
    """

    active_application_id: UUID | None = Field(default=None, alias="activeApplicationId")
    # The agenda item the room handles now. ``null`` clears it. Needs
    # ``canManageVotes``: the protokollant or the session lead.
    current_agenda_item_id: UUID | None = Field(default=None, alias="currentAgendaItemId")
    status: MeetingStatus | None = None
    date: _date | None = None
    start_time: _time | None = Field(default=None, alias="startTime")
    end_time: _time | None = Field(default=None, alias="endTime")
    protokollant_id: UUID | None = Field(default=None, alias="protokollantId")

    @model_validator(mode="after")
    def _at_least_one(self) -> MeetingPatch:
        managed = {
            "date",
            "start_time",
            "end_time",
            "protokollant_id",
            "current_agenda_item_id",
        } & self.model_fields_set
        if self.status is None and self.active_application_id is None and not managed:
            raise ValueError(
                "at least one of 'status', 'activeApplicationId', 'currentAgendaItemId', "
                "'date', 'startTime', 'endTime' or 'protokollantId' required"
            )
        return self


class MeetingVoteOut(_CamelModel):
    """A vote bound to the meeting (for meeting control)."""

    id: UUID
    # ``None`` marks a generic question on a free-text agenda item, with no
    # application behind it.
    application_id: UUID | None = Field(default=None, alias="applicationId")
    # The frontend groups the votes by this agenda item.
    agenda_item_id: UUID | None = Field(default=None, alias="agendaItemId")
    question: str | None = None
    options: list[str] = Field(default_factory=list)
    # ``cancelled``: somebody moved the application out of the vote state by hand,
    # which aborts the vote.
    status: Literal["draft", "open", "closed", "cancelled"]
    result: str | None = None
    # Current tally, option to count, plus the leading option. Both survive a
    # reload.
    counts: dict[str, int] | None = None
    leading: str | None = None
    # Participation progress: voted against present. ``revealed`` tells whether
    # ``counts`` and ``leading`` are visible. They are visible after the close, or
    # when every present member voted and the vote is not secret. Otherwise they
    # stay hidden.
    voted: int = 0
    present: int = 0
    revealed: bool = True
    # Reason for the rejection after the close: ``quorum`` for a missed quorum,
    # ``majority`` for a missed majority. The value stays ``None`` while the vote is
    # open and on ``passed`` or ``tie``.
    failed_reason: Literal["quorum", "majority"] | None = Field(
        default=None, alias="failedReason"
    )


class MeetingOut(_CamelModel):
    """Meeting state (``GET /api/meetings/{id}``)."""

    id: UUID
    gremium_id: UUID = Field(alias="gremiumId")
    gremium_name: str | None = Field(default=None, alias="gremiumName")
    title: str
    date: _date | None = None
    start_time: _time | None = Field(default=None, alias="startTime")
    end_time: _time | None = Field(default=None, alias="endTime")
    # The close sets this field. It fills the end line of the protocol title page.
    closed_at: _datetime | None = Field(default=None, alias="closedAt")
    status: MeetingStatus
    active_application_id: UUID | None = Field(default=None, alias="activeApplicationId")
    # The agenda item the room handles now. Followers and the beamer follow it.
    current_agenda_item_id: UUID | None = Field(default=None, alias="currentAgendaItemId")
    protocol_id: UUID | None = Field(default=None, alias="protocolId")
    created_at: _datetime = Field(alias="createdAt")
    protokollant_id: UUID | None = Field(default=None, alias="protokollantId")
    protokollant_name: str | None = Field(default=None, alias="protokollantName")
    # The server resolves this flag, because the frontend knows only ``sub`` and not
    # the internal principal id.
    is_protokollant: bool = Field(default=False, alias="isProtokollant")
    # Master flag for the frontend: the principal may lead the meeting, which covers
    # the protocol, the agenda items and the status. It holds for the protokollant
    # and for a meeting manager. The granular flags follow below.
    can_control: bool = Field(default=False, alias="canControl")
    can_manage: bool = Field(default=False, alias="canManage")
    can_write: bool = Field(default=False, alias="canWrite")
    can_manage_votes: bool = Field(default=False, alias="canManageVotes")
    can_vote: bool = Field(default=False, alias="canVote")
    votes: list[MeetingVoteOut] = Field(default_factory=list)


TimelineDirection = Literal["past", "upcoming"]


class MeetingPage(_CamelModel):
    """Cursor page of the meeting timeline.

    The page is keyset-paginated around *now*. ``upcoming`` runs forward (earliest
    first). ``past`` runs backward (latest first). ``nextCursor`` is ``None`` when
    no further meeting follows in that direction.
    """

    items: list[MeetingOut]
    next_cursor: str | None = Field(default=None, alias="nextCursor")


class MeetingGremiumOut(_CamelModel):
    """Gremium (id and name) for the meeting-overview filter.

    The source is visibility, not membership. A Gremium appears exactly when the
    principal can read at least one meeting there. A pool substitute or a
    delegation recipient without a membership can therefore filter their Gremium. A
    member of a Gremium without meetings does not get the entry.
    """

    id: UUID
    name: str


AttendanceStatus = Literal["present", "excused", "absent"]


class AttendanceOut(_CamelModel):
    """Attendance of a Gremium member for a meeting."""

    principal_id: UUID = Field(alias="principalId")
    display_name: str | None = Field(default=None, alias="displayName")
    email: str | None = None
    # ``None`` means not yet recorded: a roster member without an entry.
    status: AttendanceStatus | None = None
    source: Literal["self", "lead"] | None = None
    # True when the requesting principal is this member, which allows self-marking.
    is_self: bool = Field(default=False, alias="isSelf")


class MeetingMemberOut(_CamelModel):
    """Current Gremium member, as a protokollant candidate for a new meeting."""

    principal_id: UUID = Field(alias="principalId")
    display_name: str | None = Field(default=None, alias="displayName")
    email: str | None = None


class AttendanceSetBody(_CamelModel):
    """``PUT …/attendance/{principalId}`` or ``…/me`` — set attendance."""

    status: AttendanceStatus


class AgendaItemOut(_CamelModel):
    """Agenda item: an assigned application or a free-text item."""

    id: UUID
    application_id: UUID | None = Field(default=None, alias="applicationId")
    title: str | None = None
    # Markdown text of this agenda item.
    body: str | None = None
    position: int = 0
    # The public protocol PDF redacts a non-public agenda item.
    non_public: bool = Field(default=False, alias="nonPublic")
    # Current application status as an i18n label.
    state_label: dict[str, str] | None = Field(default=None, alias="stateLabel")


class AssignableApplicationOut(_CamelModel):
    """Application of the meeting Gremium in a vote state, not yet on the agenda."""

    application_id: UUID = Field(alias="applicationId")
    title: str | None = None
    state_label: dict[str, str] | None = Field(default=None, alias="stateLabel")


class MeetingVoteOpenBody(_CamelModel):
    """``POST /meetings/{id}/votes`` — open a live vote on an agenda item.

    The route binds a new vote to the agenda item (``agendaItemId``) and opens it at
    once. An application agenda item allows exactly one vote, because that vote
    fires the pass or fail branch of the application on close. A free-text agenda
    item allows several generic questions. ``question`` goes into the protocol
    snippet.
    """

    agenda_item_id: UUID = Field(alias="agendaItemId")
    question: str | None = None
    options: list[str] = Field(default_factory=lambda: ["yes", "no", "abstain"])
    majority_rule: Literal["simple", "absolute", "two_thirds"] = Field(
        default="simple", alias="majorityRule"
    )
    secret: bool = False
    # The server always derives the quorum denominator from the current roster
    # through ``vote_eligible_count``. It never comes from the client, so nobody can
    # manipulate it against the real roster. This field holds an explicit percent
    # quorum from 0 to 100. ``None`` selects the Gremium default when the Gremium
    # sets one.
    quorum_percent: int | None = Field(
        default=None, alias="quorumPercent", ge=0, le=100
    )

    @model_validator(mode="after")
    def _min_options(self) -> MeetingVoteOpenBody:
        if len(self.options) < 2:
            raise ValueError("at least two options are required")
        return self


class AgendaAddBody(_CamelModel):
    """``POST /meetings/{id}/agenda`` — add an agenda item, application or free text.

    Supply exactly one of ``applicationId`` and ``title``.
    """

    application_id: UUID | None = Field(default=None, alias="applicationId")
    title: str | None = Field(default=None, min_length=1)
    non_public: bool = Field(default=False, alias="nonPublic")

    @model_validator(mode="after")
    def _one_of(self) -> AgendaAddBody:
        if (self.application_id is None) == (self.title is None):
            raise ValueError("exactly one of applicationId or title is required")
        return self


class AgendaBodyBody(_CamelModel):
    """``PATCH …/agenda/{itemId}`` — set the markdown body or the title of an item.

    ``title`` renames only a free-text agenda item. An application agenda item
    inherits the title from the application. ``body`` sets the markdown text. Both
    fields are optional.
    """

    body: str | None = None
    title: str | None = Field(default=None, min_length=1)
    non_public: bool | None = Field(default=None, alias="nonPublic")


class AgendaReorderBody(_CamelModel):
    """``PUT …/agenda/order`` — order the agenda items as supplied."""

    item_ids: list[UUID] = Field(alias="itemIds")
