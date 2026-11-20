"""Response models of the tab "Gremien" (camelCase JSON).

Every model reads only, except ``GremiumInfoIn``, the save of the Info tab. The excuse
text of an attendance (``meeting_attendance.note``) is in no model, also not for the
person: the tab shows the status only.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date as _date
from datetime import datetime as _datetime
from datetime import time as _time
from decimal import Decimal
from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, StringConstraints, field_validator
from pydantic.alias_generators import to_camel

from app.shared.schemas import FrozenStrictCamelModel

MeetingStatus = Literal["planned", "live", "closed"]
ProtocolStatus = Literal["draft", "rendering", "final"]
#: ``seat`` and ``no_seat`` are the states of a pool substitute (§F/meetings/meetings/001311).
AttendanceState = Literal["present", "excused", "absent", "delegated", "seat", "no_seat"]
DecisionKind = Literal["application", "election", "motion"]
DecisionResultFilter = Literal["passed", "rejected"]


class _GremienOut(FrozenStrictCamelModel, frozen=True):
    """Base of the models: frozen, camelCase in JSON, fields fillable by name, no extra field."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", alias_generator=to_camel)


class NextMeetingOut(_GremienOut, frozen=True):
    """The live meeting of a gremium, else its next planned meeting."""

    id: UUID
    title: str
    date: _date | None
    start_time: _time | None
    status: MeetingStatus


class GremiumOverviewOut(_GremienOut, frozen=True):
    """One row of the list of gremien."""

    id: UUID
    name: str
    slug: str
    is_member: bool
    role_key: str | None
    role_name: Mapping[str, str] | None
    member_count: int
    next_meeting: NextMeetingOut | None
    live: bool
    quorum_percent: int | None
    quorum_min_present: int | None
    protocols_public: bool
    allow_vote_delegation: bool
    logo_url: str | None


class GremiumMemberOut(_GremienOut, frozen=True):
    """One membership of a gremium, with the name, the e-mail and the role."""

    principal_id: UUID
    display_name: str | None
    email: str | None
    role_id: UUID
    role_key: str
    role_name: Mapping[str, str]
    is_self: bool


class GremiumMeetingOut(_GremienOut, frozen=True):
    """One meeting of a gremium, with the attendance and the protocol state."""

    id: UUID
    title: str
    date: _date | None
    start_time: _time | None
    end_time: _time | None
    status: MeetingStatus
    agenda_item_count: int
    present_count: int
    member_count: int
    protocol_status: ProtocolStatus | None
    #: The final protocol carries the approval mark (§F/meetings/protocols/000924).
    protocol_approved: bool


class AttendanceMonthOut(_GremienOut, frozen=True):
    """One month of the range: ``YYYY-MM`` and the number of closed meetings."""

    month: str
    meetings: int


class AttendanceCellOut(_GremienOut, frozen=True):
    """The attendance of one member in one month.

    ``member`` tells whether the principal holds a membership in the gremium.
    ``delegated`` counts the meetings in which the member transferred the vote. A
    meeting without a record counts as absent and appears in no number.

    In a row with ``pool``, ``member`` is always true and ``present`` counts the pool
    seats of the month; ``excused`` and ``delegated`` are 0.
    """

    month: str
    member: bool
    present: int
    excused: int
    delegated: int


class AttendanceRowOut(_GremienOut, frozen=True):
    """One person of the attendance matrix.

    A row with ``pool`` is a pool substitute of the gremium (§F/meetings/meetings/001310):
    no role, no unexcused absences, and its cells count pool seats.
    """

    principal_id: UUID
    display_name: str | None
    role_key: str | None
    role_name: Mapping[str, str] | None
    is_self: bool
    #: The unexcused absences of the chosen term: closed ordinary meetings with the
    #: status ``absent`` (§F/meetings/meetings/000920).
    unexcused: int
    cells: tuple[AttendanceCellOut, ...]
    pool: bool = False


class AttendanceOut(_GremienOut, frozen=True):
    """The attendance matrix of a gremium for a range of months.

    ``unexcused`` of a row counts the term that starts on ``termStart``, whatever the
    range of months is. ``terms`` holds the first day of each term on offer, the newest
    first (§F/meetings/meetings/000941).
    """

    from_month: str
    to_month: str
    #: The first day of the chosen term, and the number of unexcused absences in one
    #: term that ends a Mandat.
    term_start: _date
    terms: list[_date]
    absence_limit: int
    months: list[AttendanceMonthOut]
    rows: list[AttendanceRowOut]


class MemberMeetingOut(_GremienOut, frozen=True):
    """One closed meeting of a month with the state of one member."""

    meeting_id: UUID
    title: str
    date: _date | None
    start_time: _time | None
    status: AttendanceState
    #: The delegate of a ``delegated`` meeting, or the represented member of a ``seat``.
    delegate_name: str | None
    #: The end of the late-excuse window, only on the own ``absent`` row while the
    #: window is open (§F/meetings/meetings/000922).
    late_excuse_until: _datetime | None = None


class MemberAttendanceOut(_GremienOut, frozen=True):
    """The closed meetings of one month with the state of one member."""

    principal_id: UUID
    display_name: str | None
    month: str
    meetings: list[MemberMeetingOut]


class DecisionCountsOut(_GremienOut, frozen=True):
    """The sums of a closed motion: never a voter."""

    yes: int
    no: int
    abstain: int


class DecisionOut(_GremienOut, frozen=True):
    """One closed vote of a gremium."""

    id: UUID
    question: str | None
    kind: DecisionKind
    application_id: UUID | None
    application_title: str | None
    amount: Decimal | None
    secret: bool
    majority_rule: str | None
    counts: DecisionCountsOut | None
    ballots: int
    result: str | None
    elected: list[str]
    meeting_id: UUID | None
    meeting_title: str | None
    meeting_date: _date | None
    closed_at: _datetime | None


class DecisionPageOut(_GremienOut, frozen=True):
    """One page of decisions, newest first. ``nextCursor`` is null on the last page."""

    items: list[DecisionOut]
    next_cursor: str | None


#: The schemes that an Info link may use. Every other scheme (``javascript:``,
#: ``data:``, ...) would run in the browser of every reader, so the server refuses it.
INFO_LINK_SCHEMES: Final = ("https://", "http://", "mailto:")
INFO_MAX_LINKS: Final = 30
INFO_MAX_TEXT: Final = 20_000


class GremiumInfoLink(_GremienOut, frozen=True):
    """One labelled link of the Info tab: a label of 1 to 80 characters and a URL."""

    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]

    @field_validator("url")
    @classmethod
    def _known_scheme(cls, value: str) -> str:
        """Refuse a URL whose scheme is not ``https``, ``http`` or ``mailto``."""
        lower = value.lower()
        if not any(lower.startswith(s) and len(lower) > len(s) for s in INFO_LINK_SCHEMES):
            raise ValueError("the url must start with https://, http:// or mailto:")
        return value


class GremiumInfoIn(_GremienOut, frozen=True):
    """A save of the Info tab: the text, the links in their order and the version read."""

    body_md: str = Field(default="", max_length=INFO_MAX_TEXT)
    links: tuple[GremiumInfoLink, ...] = Field(default=(), max_length=INFO_MAX_LINKS)
    version: int = Field(ge=0)


class GremiumInfoOut(_GremienOut, frozen=True):
    """The Info tab of a Gremium. An unsaved Info is empty with version 0.

    ``canEdit`` tells if the caller holds ``info.write`` in the Gremium.
    """

    body_md: str
    links: tuple[GremiumInfoLink, ...]
    version: int
    updated_at: _datetime | None
    updated_by_name: str | None
    can_edit: bool


#: The limits of a message to the members (spec 001854).
NOTIFY_MAX_SUBJECT: Final = 200
NOTIFY_MAX_MESSAGE: Final = 10_000


class GremiumNotifyIn(_GremienOut, frozen=True):
    """A message to the members: a subject and a plain text, both not blank."""

    subject: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NOTIFY_MAX_SUBJECT)
    ]
    message: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NOTIFY_MAX_MESSAGE)
    ]


class GremiumNotifyOut(_GremienOut, frozen=True):
    """The result of a send: the number of recipients, never their addresses."""

    recipients: int
