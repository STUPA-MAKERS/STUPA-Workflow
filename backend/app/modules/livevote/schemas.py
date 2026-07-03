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
    """camelCase aliases in JSON; fields settable by name."""

    model_config = ConfigDict(populate_by_name=True)


class MeetingCreate(_CamelModel):
    """``POST /api/meetings`` — create a meeting (status ``planned``)."""

    gremium_id: UUID = Field(alias="gremiumId")
    title: str = Field(min_length=1)
    # Date is required: a meeting can't be scheduled without one.
    date: _date
    start_time: _time = Field(alias="startTime")
    # Optional end time; if unset the iCal feed assumes a 1h duration.
    end_time: _time | None = Field(default=None, alias="endTime")
    # Exactly one assigned protokollant (a committee member).
    protokollant_id: UUID | None = Field(default=None, alias="protokollantId")

    @model_validator(mode="after")
    def _end_after_start(self) -> MeetingCreate:
        if self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("endTime must be after startTime")
        return self


class MeetingPatch(_CamelModel):
    """``PATCH /api/meetings/{id}`` — control/plan a meeting.

    At least one field must be set; any change publishes ``meeting_state``.
    """

    active_application_id: UUID | None = Field(default=None, alias="activeApplicationId")
    status: MeetingStatus | None = None
    date: _date | None = None
    start_time: _time | None = Field(default=None, alias="startTime")
    end_time: _time | None = Field(default=None, alias="endTime")
    protokollant_id: UUID | None = Field(default=None, alias="protokollantId")

    @model_validator(mode="after")
    def _at_least_one(self) -> MeetingPatch:
        # ``date``/``protokollantId`` count too: schedule a planned meeting or
        # (re)assign its protokollant.
        managed = {
            "date",
            "start_time",
            "end_time",
            "protokollant_id",
        } & self.model_fields_set
        if self.status is None and self.active_application_id is None and not managed:
            raise ValueError(
                "at least one of 'status', 'activeApplicationId', 'date', "
                "'startTime', 'endTime' or 'protokollantId' required"
            )
        return self


class MeetingVoteOut(_CamelModel):
    """A vote bound to the meeting (for session control)."""

    id: UUID
    # NULL = generic question (free-text TOP), no application.
    application_id: UUID | None = Field(default=None, alias="applicationId")
    # Which TOP the vote is bound to (for grouping in the FE).
    agenda_item_id: UUID | None = Field(default=None, alias="agendaItemId")
    question: str | None = None
    # Options (for casting in the FE).
    options: list[str] = Field(default_factory=list)
    # ``cancelled``: the application left the vote state manually (vote aborted).
    status: Literal["draft", "open", "closed", "cancelled"]
    result: str | None = None
    # Current tally (option → count) + leading option; survives a reload.
    counts: dict[str, int] | None = None
    leading: str | None = None
    # Participation progress (voted vs. present) + ``revealed``: whether
    # ``counts``/``leading`` are visible (closed, or all present voted and not
    # secret), otherwise hidden.
    voted: int = 0
    present: int = 0
    revealed: bool = True
    # Rejection reason (after close): ``quorum`` = quorum missed, ``majority`` =
    # majority missed. ``None`` while open or on ``passed``/``tie``.
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
    # Set automatically on close — end line of the protocol title page.
    closed_at: _datetime | None = Field(default=None, alias="closedAt")
    status: MeetingStatus
    active_application_id: UUID | None = Field(default=None, alias="activeApplicationId")
    protocol_id: UUID | None = Field(default=None, alias="protocolId")
    created_at: _datetime = Field(alias="createdAt")
    protokollant_id: UUID | None = Field(default=None, alias="protokollantId")
    protokollant_name: str | None = Field(default=None, alias="protokollantName")
    # Is the requesting principal this meeting's protokollant? Resolved
    # server-side because the FE knows only ``sub``, not the internal principal_id.
    is_protokollant: bool = Field(default=False, alias="isProtokollant")
    # Master flag for the FE: may the principal lead the meeting (protocol/TOPs/
    # status)? = protokollant or session manager. Granular flags below.
    can_control: bool = Field(default=False, alias="canControl")
    can_manage: bool = Field(default=False, alias="canManage")
    can_write: bool = Field(default=False, alias="canWrite")
    can_manage_votes: bool = Field(default=False, alias="canManageVotes")
    can_vote: bool = Field(default=False, alias="canVote")
    # Votes bound to the meeting (session control).
    votes: list[MeetingVoteOut] = Field(default_factory=list)


TimelineDirection = Literal["past", "upcoming"]


class MeetingPage(_CamelModel):
    """Cursor page of the meeting timeline.

    Keyset-paginated around *now*: ``upcoming`` runs forward (earliest first),
    ``past`` backward (latest first). ``nextCursor`` is ``None`` once no further
    meetings follow in that direction.
    """

    items: list[MeetingOut]
    next_cursor: str | None = Field(default=None, alias="nextCursor")


class MeetingGremiumOut(_CamelModel):
    """Committee (id + name) for the meeting-overview filter.

    Source is visibility, not membership: a committee appears iff the principal
    has at least one readable meeting there. So a pool substitute/delegation
    recipient without membership can filter their committee, while a member of a
    meeting-less committee isn't offered it.
    """

    id: UUID
    name: str


AttendanceStatus = Literal["present", "excused", "absent"]


class AttendanceOut(_CamelModel):
    """Attendance of a committee member for a meeting."""

    principal_id: UUID = Field(alias="principalId")
    display_name: str | None = Field(default=None, alias="displayName")
    email: str | None = None
    # ``None`` = not yet recorded (roster member without an entry).
    status: AttendanceStatus | None = None
    source: Literal["self", "lead"] | None = None
    # Is the requesting principal this member (for self-marking)?
    is_self: bool = Field(default=False, alias="isSelf")


class MeetingMemberOut(_CamelModel):
    """Current committee member — protokollant candidate when creating a meeting."""

    principal_id: UUID = Field(alias="principalId")
    display_name: str | None = Field(default=None, alias="displayName")
    email: str | None = None


class AttendanceSetBody(_CamelModel):
    """``PUT …/attendance/{principalId}`` or ``…/me`` — set attendance."""

    status: AttendanceStatus


class AgendaItemOut(_CamelModel):
    """Agenda item: an assigned application or free-text TOP."""

    id: UUID
    application_id: UUID | None = Field(default=None, alias="applicationId")
    title: str | None = None
    # Markdown body of this TOP (per-TOP editor).
    body: str | None = None
    position: int = 0
    # Non-public: redacted in the public protocol PDF.
    non_public: bool = Field(default=False, alias="nonPublic")
    # Current application status (i18n label), e.g. to show in the list.
    state_label: dict[str, str] | None = Field(default=None, alias="stateLabel")


class AssignableApplicationOut(_CamelModel):
    """Application in a vote state of the meeting's committee (not yet on the agenda)."""

    application_id: UUID = Field(alias="applicationId")
    title: str | None = None
    state_label: dict[str, str] | None = Field(default=None, alias="stateLabel")


class MeetingVoteOpenBody(_CamelModel):
    """``POST /meetings/{id}/votes`` — open a live vote on a TOP.

    Binds a new vote to the TOP (``agendaItemId``) and opens it at once.
    Application TOPs allow exactly one vote (it fires the application's pass/fail
    branch on close); free-text TOPs allow several generic questions.
    ``question`` goes into the protocol snippet.
    """

    agenda_item_id: UUID = Field(alias="agendaItemId")
    question: str | None = None
    options: list[str] = Field(default_factory=lambda: ["yes", "no", "abstain"])
    majority_rule: Literal["simple", "absolute", "two_thirds"] = Field(
        default="simple", alias="majorityRule"
    )
    secret: bool = False
    # The quorum denominator is always derived server-side from the current
    # roster (``vote_eligible_count``), never a client input, so it can't be
    # manipulated against the real roster.
    # Explicit percent quorum (0–100). ``None`` ⇒ committee default (if set).
    quorum_percent: int | None = Field(
        default=None, alias="quorumPercent", ge=0, le=100
    )

    @model_validator(mode="after")
    def _min_options(self) -> MeetingVoteOpenBody:
        if len(self.options) < 2:
            raise ValueError("at least two options are required")
        return self


class AgendaAddBody(_CamelModel):
    """``POST /meetings/{id}/agenda`` — add a TOP: application or free-text.

    Exactly one of ``applicationId`` / ``title`` is required.
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
    """``PATCH …/agenda/{itemId}`` — set a TOP's markdown body and/or title.

    ``title`` renames only free-text TOPs (application TOPs inherit the title
    from the application); ``body`` sets the markdown text. Both optional.
    """

    body: str | None = None
    title: str | None = Field(default=None, min_length=1)
    non_public: bool | None = Field(default=None, alias="nonPublic")


class AgendaReorderBody(_CamelModel):
    """``PUT …/agenda/order`` — order TOPs as supplied."""

    item_ids: list[UUID] = Field(alias="itemIds")
