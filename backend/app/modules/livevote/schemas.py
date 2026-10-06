"""API schemas for the live-vote/meeting module."""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime as _datetime
from datetime import time as _time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.voting.schemas import MyBallot
from app.shared.config_schemas import Quorum
from app.shared.i18n import I18nMap

MeetingStatus = Literal["planned", "live", "closed"]
# #17: admitted guests of a public meeting vote (`vote`) or only follow it (`watch`).
GuestsMode = Literal["vote", "watch"]


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
    # #17: public participation with the QR code, and what the admitted guests do.
    public_join: bool = Field(default=False, alias="publicJoin")
    guests_mode: GuestsMode = Field(default="vote", alias="guestsMode")

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
    # #17: public participation and the guest mode. Both need ``canManage``. Switching
    # ``publicJoin`` off voids the open requests and removes the admitted guests.
    public_join: bool | None = Field(default=None, alias="publicJoin")
    guests_mode: GuestsMode | None = Field(default=None, alias="guestsMode")

    @model_validator(mode="after")
    def _at_least_one(self) -> MeetingPatch:
        managed = {
            "date",
            "start_time",
            "end_time",
            "protokollant_id",
            "current_agenda_item_id",
        } & self.model_fields_set
        public = self.public_join is not None or self.guests_mode is not None
        if (
            self.status is None
            and self.active_application_id is None
            and not managed
            and not public
        ):
            raise ValueError(
                "at least one of 'status', 'activeApplicationId', 'currentAgendaItemId', "
                "'date', 'startTime', 'endTime', 'protokollantId', 'publicJoin' or "
                "'guestsMode' required"
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
    # The rules of the vote, for the vote card (A5).
    majority_rule: Literal["simple", "absolute", "two_thirds"] = Field(
        default="simple", alias="majorityRule"
    )
    secret: bool = False
    quorum: Quorum | None = None
    # The real open time (``opens_at``) and the real end time (close or cancel).
    opened_at: _datetime | None = Field(default=None, alias="openedAt")
    closed_at: _datetime | None = Field(default=None, alias="closedAt")
    # The own ballot of the caller. A secret vote gives only ``cast``. None when the
    # payload has no caller (a broadcast).
    my_ballot: MyBallot | None = Field(default=None, alias="myBallot")
    # True when the caller cast the ballot of a delegator in this vote.
    represented_cast: bool = Field(default=False, alias="representedCast")
    # #17: the admitted guests vote too (no quorum, majority of the cast ballots).
    guests_vote: bool = Field(default=False, alias="guestsVote")
    # #17: the present members and the admitted guests, live while the vote runs and
    # fixed at the close. For a vote with guests ``present`` is their sum.
    present_members: int | None = Field(default=None, alias="presentMembers")
    present_guests: int | None = Field(default=None, alias="presentGuests")


class CurrentAgendaItemOut(_CamelModel):
    """The agenda item the room handles now, for the start page and the timeline (A2)."""

    # The 1-based number of the item in the agenda order ("TOP 3").
    position: int
    # The title of a free-text item, or the title of the application.
    title: str | None = None


class KeeperPeriodOut(_CamelModel):
    """One period of a protocol keeper (Z3, A13).

    ``fromAt`` is ``None`` for the planned handover. ``toAt`` is ``None`` while the
    period runs. The positions are the 1-based numbers of the agenda items in the
    current agenda order. A position is ``None`` when the period has no item there
    or the item no longer exists; a reader then shows the time.
    """

    principal_id: UUID = Field(alias="principalId")
    name: str | None = None
    from_at: _datetime | None = Field(default=None, alias="fromAt")
    to_at: _datetime | None = Field(default=None, alias="toAt")
    from_agenda_item_id: UUID | None = Field(default=None, alias="fromAgendaItemId")
    to_agenda_item_id: UUID | None = Field(default=None, alias="toAgendaItemId")
    from_position: int | None = Field(default=None, alias="fromPosition")
    to_position: int | None = Field(default=None, alias="toPosition")


HandoverMode = Literal["now", "next_item"]


class ProtokollantHandoverBody(_CamelModel):
    """``POST /meetings/{id}/protokollant-handover`` — hand the minutes over (Z3, O1).

    ``now`` hands over at once. ``next_item`` plans the handover for the next
    forward move of the current agenda item.
    """

    principal_id: UUID = Field(alias="principalId")
    mode: HandoverMode = "now"


class MeetingOut(_CamelModel):
    """Meeting state (``GET /api/meetings/{id}``)."""

    id: UUID
    gremium_id: UUID = Field(alias="gremiumId")
    gremium_name: str | None = Field(default=None, alias="gremiumName")
    title: str
    date: _date | None = None
    start_time: _time | None = Field(default=None, alias="startTime")
    end_time: _time | None = Field(default=None, alias="endTime")
    # The real start (Z7). The start sets it once. ``None`` for a meeting that has not
    # started, or that started before the field existed: a reader then uses the
    # planned start.
    started_at: _datetime | None = Field(default=None, alias="startedAt")
    # The close sets this field. It fills the end line of the protocol title page.
    closed_at: _datetime | None = Field(default=None, alias="closedAt")
    status: MeetingStatus
    active_application_id: UUID | None = Field(default=None, alias="activeApplicationId")
    # The agenda item the room handles now. Followers and the beamer follow it.
    current_agenda_item_id: UUID | None = Field(default=None, alias="currentAgendaItemId")
    # A2: number and title of the current agenda item, and the size of the agenda. The
    # reader of the meeting also reads its agenda, so both carry no new data.
    current_agenda_item: CurrentAgendaItemOut | None = Field(
        default=None, alias="currentAgendaItem"
    )
    agenda_item_count: int = Field(default=0, alias="agendaItemCount")
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
    # The principal may finalize and send the protocol: the write access plus the
    # gremium permission ``protocol.finalize``.
    can_finalize: bool = Field(default=False, alias="canFinalize")
    votes: list[MeetingVoteOut] = Field(default_factory=list)
    # A13: the periods of the protocol keepers in time order (running and ended),
    # and the planned handover of the next agenda item.
    keeper_periods: list[KeeperPeriodOut] = Field(default_factory=list, alias="keeperPeriods")
    planned_handover: KeeperPeriodOut | None = Field(default=None, alias="plannedHandover")
    # #17: public participation with the QR code. ``joinCode`` goes only to a caller
    # with ``canManage``, ``pendingGuests`` too (0 for everybody else).
    public_join: bool = Field(default=False, alias="publicJoin")
    guests_mode: GuestsMode = Field(default="vote", alias="guestsMode")
    join_code: str | None = Field(default=None, alias="joinCode")
    admitted_guests: int = Field(default=0, alias="admittedGuests")
    pending_guests: int = Field(default=0, alias="pendingGuests")


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
# A member reports only "present" or "excused" for the own record (Z2). Only the
# meeting lead records "absent", that is absent without an excuse.
SelfAttendanceStatus = Literal["present", "excused"]
# Upper limit for the reason of an excuse. The reason is personal data, so keep it short.
ATTENDANCE_NOTE_MAX = 500


class AttendanceOut(_CamelModel):
    """Attendance of a Gremium member for a meeting."""

    principal_id: UUID = Field(alias="principalId")
    display_name: str | None = Field(default=None, alias="displayName")
    email: str | None = None
    # ``None`` means not yet recorded: a roster member without an entry.
    status: AttendanceStatus | None = None
    source: Literal["self", "lead"] | None = None
    # The reason of an excuse (A7). It is personal data: only the member and the
    # meeting lead (``canWrite``) see it. All other readers get ``None``.
    note: str | None = None
    # True when the requesting principal is this member, which allows self-marking.
    is_self: bool = Field(default=False, alias="isSelf")
    # O20: the member holds the gremium permission ``protocol.write`` and can keep
    # the minutes. The keeper pickers offer only these members.
    can_keep_protocol: bool = Field(default=False, alias="canKeepProtocol")
    # The member has an own vote now (gremium permission ``vote.cast``). Only such a
    # member can delegate, so the lead offers "Vertretung eintragen" only for them (O6).
    can_vote: bool = Field(default=False, alias="canVote")
    # A8: name of the faculty group of the member (Z5), or ``None`` without one.
    substitute_group_name: I18nMap | None = Field(default=None, alias="substituteGroupName")


class MeetingMemberOut(_CamelModel):
    """Current Gremium member, as a protokollant candidate for a new meeting."""

    principal_id: UUID = Field(alias="principalId")
    display_name: str | None = Field(default=None, alias="displayName")
    email: str | None = None
    # O20: only a member with the gremium permission ``protocol.write`` can keep the
    # minutes. Another member gives 422 ``protokollant_needs_protocol_write``.
    can_keep_protocol: bool = Field(default=False, alias="canKeepProtocol")
    # A8: name of the faculty group of the member (Z5), or ``None`` without one.
    substitute_group_name: I18nMap | None = Field(default=None, alias="substituteGroupName")


class _AttendanceNoteBody(_CamelModel):
    """Shared ``note`` field of the attendance bodies.

    ``note`` is the reason of an excuse. It is allowed only with ``excused``, else
    422. An omitted ``note`` keeps the stored reason while the status stays
    ``excused``. An explicit ``null`` or an empty text removes it. Any status other
    than ``excused`` removes the stored reason.
    """

    note: str | None = Field(default=None, max_length=ATTENDANCE_NOTE_MAX)

    @property
    def note_given(self) -> bool:
        """Return True when the body sets ``note``, also when it sets ``null``."""
        return "note" in self.model_fields_set

    def clean_note(self) -> str | None:
        """Return the stripped note, or ``None`` for an empty text."""
        text = (self.note or "").strip()
        return text or None


def _note_only_when_excused(status: str, note: str | None) -> None:
    if status != "excused" and (note or "").strip():
        raise ValueError("note is allowed only with status 'excused'")


class AttendanceSetBody(_AttendanceNoteBody):
    """``PUT …/attendance/{principalId}`` — the meeting lead sets the attendance."""

    status: AttendanceStatus

    @model_validator(mode="after")
    def _note_with_excused(self) -> AttendanceSetBody:
        _note_only_when_excused(self.status, self.note)
        return self


class AttendanceSelfBody(_AttendanceNoteBody):
    """``PUT …/attendance/me`` — a member reports the own attendance.

    Only ``present`` and ``excused`` are allowed (Z2). ``absent`` gives 422.
    """

    status: SelfAttendanceStatus

    @model_validator(mode="after")
    def _note_with_excused(self) -> AttendanceSelfBody:
        _note_only_when_excused(self.status, self.note)
        return self


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

    The body has no ``tieBreak``: a meeting vote has no casting vote, and the route
    always stores ``tieBreak=rejected`` (O18).
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
    # #17: the admitted guests vote too. ``None`` picks the default: on in a meeting
    # where guests vote, on a public agenda item; else off. Such a vote has no quorum.
    guests_vote: bool | None = Field(default=None, alias="guestsVote")

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


# Public meeting with a QR code (#17)
GuestStatus = Literal["pending", "admitted", "rejected", "removed", "left"]
# A guest name: trimmed, 2 to 80 characters. No check for duplicates (decision #17).
GUEST_NAME_MIN = 2
GUEST_NAME_MAX = 80


def clean_guest_name(value: str) -> str:
    """Trim a guest name and check its length (2 to 80 characters)."""
    name = " ".join(value.split())
    if not GUEST_NAME_MIN <= len(name) <= GUEST_NAME_MAX:
        raise ValueError(
            f"displayName must have {GUEST_NAME_MIN} to {GUEST_NAME_MAX} characters"
        )
    return name


class GuestNameBody(_CamelModel):
    """``…/rename`` and ``PATCH /public/meetings/{code}/me`` — set the guest name."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    display_name: str = Field(alias="displayName", max_length=400)

    @model_validator(mode="after")
    def _clean(self) -> GuestNameBody:
        self.display_name = clean_guest_name(self.display_name)
        return self


class MeetingGuestOut(_CamelModel):
    """A guest of a public meeting, as the meeting lead sees it.

    ``displayName`` is ``None`` after the pseudonymization; the client then shows
    "Gast {number}".
    """

    id: UUID
    number: int
    display_name: str | None = Field(default=None, alias="displayName")
    # ``expired`` appears only in a ``guest_updated`` event: the row is gone (a voided
    # request).
    status: Literal["pending", "admitted", "rejected", "removed", "left", "expired"]
    requested_at: _datetime = Field(alias="requestedAt")
    decided_at: _datetime | None = Field(default=None, alias="decidedAt")
    decided_by_name: str | None = Field(default=None, alias="decidedByName")
    admitted_at: _datetime | None = Field(default=None, alias="admittedAt")


class QrMatrixOut(_CamelModel):
    """A QR code as a module matrix without the quiet zone (rows of ``0``/``1``)."""

    size: int
    rows: list[str]


class JoinLinkOut(_CamelModel):
    """The join link of a public meeting: code, absolute URL and its QR code."""

    join_code: str = Field(alias="joinCode")
    join_url: str = Field(alias="joinUrl")
    qr: QrMatrixOut
