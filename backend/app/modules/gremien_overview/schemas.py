"""Response models of the tab "Gremien" (camelCase JSON).

Every model reads only. The excuse text of an attendance (``meeting_attendance.note``)
is in no model, also not for the person: the tab shows the status only.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date as _date
from datetime import datetime as _datetime
from datetime import time as _time
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict
from pydantic.alias_generators import to_camel

from app.shared.schemas import FrozenStrictCamelModel

MeetingStatus = Literal["planned", "live", "closed"]
ProtocolStatus = Literal["draft", "rendering", "final"]
AttendanceState = Literal["present", "excused", "absent", "delegated"]
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
    """

    month: str
    member: bool
    present: int
    excused: int
    delegated: int


class AttendanceRowOut(_GremienOut, frozen=True):
    """One person of the attendance matrix."""

    principal_id: UUID
    display_name: str | None
    role_key: str | None
    role_name: Mapping[str, str] | None
    is_self: bool
    #: The unexcused absences of the chosen term: closed ordinary meetings with the
    #: status ``absent`` (§F/meetings/meetings/000920).
    unexcused: int
    cells: tuple[AttendanceCellOut, ...]


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
