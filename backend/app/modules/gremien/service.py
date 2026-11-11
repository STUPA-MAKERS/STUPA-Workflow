"""The reads of the tab "Gremien".

``GremienService`` reads; it never writes and never commits. The router checks the
gate (``access.require_gremium``) before it calls a read of one gremium.

Counting rules of the attendance (``attendance``):

* Only closed meetings count, by their date (``meeting.date``).
* "present" is a ``meeting_attendance`` row with ``present``, set by the member or by
  the lead. A pool substitute who is no member of the gremium and represents a member
  in the meeting does not count. Guests have no ``meeting_attendance`` row, so they
  never count.
* "delegated" is a meeting in which the member transferred the vote
  (``meeting_delegation`` with ``delegate_voting``). Such a meeting does not count as
  excused.
* A meeting without a row counts as absent and appears in no number.
* ``member`` tells whether the principal holds a membership in the gremium. A
  membership has no term, so the value is the same in each month of a row, and a
  former member with records shows as no member.

The excuse text (``meeting_attendance.note``) is never read.
"""

from __future__ import annotations

import base64
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import date as _date
from datetime import time as _time
from decimal import Decimal
from itertools import groupby
from operator import itemgetter
from typing import Any, assert_never
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import (
    ColumnElement,
    Select,
    Text,
    and_,
    case,
    exists,
    func,
    literal,
    or_,
    select,
    true,
    union_all,
)
from sqlalchemy import cast as sql_cast
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.applications.models import Application
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.policy import GREMIUM_VIEW_ALL
from app.modules.auth.principal import Principal
from app.modules.delegations.models import MeetingDelegation
from app.modules.gremien.access import views_all
from app.modules.gremien.models import Gremium, GremiumMembership, GremiumRole
from app.modules.gremien.schemas import (
    AttendanceCellOut,
    AttendanceMonthOut,
    AttendanceOut,
    AttendanceRowOut,
    AttendanceState,
    DecisionCountsOut,
    DecisionKind,
    DecisionOut,
    DecisionPageOut,
    DecisionResultFilter,
    GremiumMeetingOut,
    GremiumMemberOut,
    GremiumOverviewOut,
    MemberAttendanceOut,
    MemberMeetingOut,
    NextMeetingOut,
)
from app.modules.livevote.agenda_service import title_of
from app.modules.livevote.models import Meeting, MeetingAgendaItem, MeetingAttendance
from app.modules.protocol.models import Protocol
from app.modules.site_config.cd_logos import ALLOWED_SQUARE_LOGO_MIME
from app.modules.site_config.models import CdVariantLogo
from app.modules.voting.election import election_config, is_election
from app.modules.voting.listing import read_scope
from app.modules.voting.models import SecretBallot, Vote
from app.modules.voting.schemas import ElectionResultOut
from app.shared.config_schemas import VoteConfig
from app.shared.errors import BadRequestError, NotFoundError, ValidationProblem
from app.shared.search import escape_like

#: The longest range of the attendance matrix, in months.
MAX_MONTHS = 24
#: The default range of the attendance matrix: the last six months.
DEFAULT_MONTHS = 6
#: The decisions per page.
DECISION_PAGE = 30
#: The slot of the square logo of a CD variant (``cd_variant_logo.slot``).
SQUARE_SLOT = "square"

INVALID_MONTH_RANGE = "invalid_month_range"
MEMBER_NOT_FOUND = "member_not_found"

_MAX_CURSOR_OFFSET = 1_000_000

#: The forced roles first, the own roles of the gremium between them and "member".
_ROLE_ORDER = {"vorstand": 0, "manager": 1, "member": 3}

Month = tuple[int, int]


def logo_url(gremium_id: UUID) -> str:
    """Return the API path of the square logo of a gremium."""
    return f"/api/committees/{gremium_id}/logo"


def month_key(month: Month) -> str:
    """Format a month: ``(2026, 5)`` gives ``2026-05``."""
    return f"{month[0]:04d}-{month[1]:02d}"


def parse_month(value: str) -> Month:
    """Parse a month: ``2026-05`` gives ``(2026, 5)``. The router checks the pattern before."""
    year, month = value.split("-", 1)
    return int(year), int(month)


def shift_month(month: Month, delta: int) -> Month:
    """Move a month by ``delta`` months."""
    index = month[0] * 12 + (month[1] - 1) + delta
    return index // 12, index % 12 + 1


def months_between(first: Month, last: Month) -> list[Month]:
    """Return every month from ``first`` to ``last``, both included."""
    count = (last[0] * 12 + last[1]) - (first[0] * 12 + first[1]) + 1
    return [shift_month(first, n) for n in range(count)]


def month_range(from_month: str | None, to_month: str | None, today: _date) -> list[Month]:
    """Return the months of the attendance matrix.

    The range defaults to the last six months up to the current month. An omitted
    start is five months before the end, an omitted end is the current month.

    Raises:
        ValidationProblem: The start is after the end, or the range holds more than
            24 months (422 ``invalid_month_range``).
    """
    last = parse_month(to_month) if to_month else (today.year, today.month)
    first = parse_month(from_month) if from_month else shift_month(last, 1 - DEFAULT_MONTHS)
    span = (last[0] * 12 + last[1]) - (first[0] * 12 + first[1]) + 1
    if span < 1 or span > MAX_MONTHS:
        raise ValidationProblem(
            f"the range must hold 1 to {MAX_MONTHS} months",
            code=INVALID_MONTH_RANGE,
            errors=[{"field": "from", "msg": f"1 to {MAX_MONTHS} months, start before end"}],
        )
    return months_between(first, last)


def encode_cursor(offset: int) -> str:
    """Encode the opaque cursor of the decision list (an offset)."""
    return base64.urlsafe_b64encode(f"o|{offset}".encode()).decode()


def decode_cursor(cursor: str | None) -> int:
    """Decode a cursor of the decision list.

    Raises:
        BadRequestError: The cursor is malformed (400 ``invalid_cursor``).
    """
    if not cursor:
        return 0
    try:
        tag, num = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
        offset = int(num)
    except ValueError as exc:
        raise BadRequestError("invalid pagination cursor", code="invalid_cursor") from exc
    if tag != "o" or offset < 0 or offset > _MAX_CURSOR_OFFSET:
        raise BadRequestError("invalid pagination cursor", code="invalid_cursor")
    return offset


def _role_rank(key: str) -> int:
    """Return the place of a role in the member list: Vorstand, Manager, own roles, Mitglied."""
    return _ROLE_ORDER.get(key, 2)


def _nested[I, V](triples: Iterable[tuple[UUID, I, V]]) -> dict[UUID, dict[I, V]]:
    """Group ``(outer, inner, value)`` triples into ``{outer: {inner: value}}``.

    The sort is stable, so a later triple with the same keys wins, as in a loop.
    """
    ordered = sorted(triples, key=itemgetter(0))
    return {
        outer: {inner: value for _, inner, value in group}
        for outer, group in groupby(ordered, key=itemgetter(0))
    }


def _next_rank(m: Meeting) -> tuple[int, _date, _time, str]:
    """Order the next meetings: live first, then dated planned ones, then undated ones."""
    return (
        0 if m.status == "live" else 1 if m.date is not None else 2,
        m.date or _date.max,
        m.start_time or _time(0, 0),
        str(m.id),
    )


def _member_order(row: GremiumMemberOut) -> tuple[int, str]:
    """Order the member list: by role, then by name or e-mail."""
    return _role_rank(row.role_key), (row.display_name or row.email or "").casefold()


def _attendance_order(row: AttendanceRowOut) -> tuple[str, str]:
    """Order the attendance matrix: by name, then by principal id."""
    return (row.display_name or "").casefold(), str(row.principal_id)


def _member_state(recorded: str | None, *, delegated: bool) -> AttendanceState:
    """Return the state of a member in one closed meeting.

    A vote transfer wins over a record; a meeting without a usable record is absent.
    """
    match (delegated, recorded):
        case (True, _):
            return "delegated"
        case (False, "present"):
            return "present"
        case (False, "excused"):
            return "excused"
        case _:
            return "absent"


def _kind_filter(kind: DecisionKind | None) -> tuple[ColumnElement[bool], ...]:
    """Return the conditions of the ``kind`` filter of the decision list."""
    match kind:
        case None:
            return ()
        case "election":
            return (Vote.kind == "election",)
        case "application":
            return (Vote.kind != "election", Vote.application_id.is_not(None))
        case "motion":
            return (Vote.kind != "election", Vote.application_id.is_(None))
        case _:
            assert_never(kind)


def _result_filter(result: DecisionResultFilter | None) -> tuple[ColumnElement[bool], ...]:
    """Return the conditions of the ``result`` filter of the decision list."""
    match result:
        case None:
            return ()
        case "passed":
            return (Vote.result.in_(("passed", "elected")),)
        case "rejected":
            return (Vote.result.in_(("rejected", "tie")),)
        case _:
            assert_never(result)


@dataclass(frozen=True, slots=True)
class _Term:
    """One membership row of a gremium."""

    principal_id: UUID
    role_key: str
    role_name: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class _Tally:
    """The part of a decision row that depends on the kind of the vote."""

    kind: DecisionKind
    counts: DecisionCountsOut | None
    elected: list[str]
    ballots: int
    secret: bool
    rule: str | None


def _election_tally(vote: Vote) -> _Tally:
    """Return the elected names and the ballots of an election, from its stored result."""
    config = election_config(vote)
    stored = ElectionResultOut.model_validate(vote.election_result or {"counts": {}})
    names = {c.id: c.name for c in config.candidates}
    return _Tally(
        kind="election",
        counts=None,
        elected=[names.get(cid, cid) for cid in stored.elected],
        ballots=stored.ballots,
        secret=config.secret,
        rule=None,
    )


def _motion_tally(vote: Vote, per: Mapping[str, int]) -> _Tally:
    """Return the sums of a motion or an application vote."""
    config = VoteConfig.from_stored(vote.config)
    return _Tally(
        kind="application" if vote.application_id else "motion",
        counts=DecisionCountsOut(
            yes=per.get("yes", 0), no=per.get("no", 0), abstain=per.get("abstain", 0)
        ),
        elected=[],
        ballots=sum(per.values()),
        secret=config.secret,
        rule=config.majority_rule,
    )


def _overview_row(
    g: Gremium,
    role: tuple[str, Mapping[str, str]] | None,
    nxt: NextMeetingOut | None,
    member_count: int,
    *,
    has_logo: bool,
) -> GremiumOverviewOut:
    """Build one row of the list of gremien."""
    return GremiumOverviewOut(
        id=g.id,
        name=g.name,
        slug=g.slug,
        is_member=role is not None,
        role_key=role[0] if role else None,
        role_name=role[1] if role else None,
        member_count=member_count,
        next_meeting=nxt,
        live=nxt is not None and nxt.status == "live",
        quorum_percent=g.quorum_percent,
        protocols_public=bool(g.protocols_public),
        allow_vote_delegation=bool(g.allow_vote_delegation),
        logo_url=logo_url(g.id) if has_logo else None,
    )


def _meeting_row(
    m: Meeting,
    recorded: Mapping[UUID, str],
    members: frozenset[UUID],
    agenda_items: int,
    protocol_status: str | None,
) -> GremiumMeetingOut:
    """Build one meeting row: the roster is the members plus every recorded principal."""
    return GremiumMeetingOut(
        id=m.id,
        title=m.title,
        date=m.date,
        start_time=m.start_time,
        end_time=m.end_time,
        status=m.status,  # type: ignore[arg-type]
        agenda_item_count=agenda_items,
        present_count=sum(1 for st in recorded.values() if st == "present"),
        member_count=len(members | recorded.keys()),
        protocol_status=protocol_status,  # type: ignore[arg-type]
    )


def _attendance_row(
    pid: UUID,
    own_terms: Sequence[_Term],
    person: tuple[str | None, str | None],
    months: Sequence[Month],
    cells: Mapping[str, tuple[int, int, int]],
    viewer_sub: str,
) -> AttendanceRowOut:
    """Build one person of the attendance matrix, with a cell for each month."""
    display, sub = person
    role = own_terms[0] if own_terms else None
    return AttendanceRowOut(
        principal_id=pid,
        display_name=display,
        role_key=role.role_key if role else None,
        role_name=role.role_name if role else None,
        is_self=sub is not None and sub == viewer_sub,
        cells=tuple(_attendance_cell(month_key(m), cells, member=bool(own_terms)) for m in months),
    )


def _attendance_cell(
    key: str, cells: Mapping[str, tuple[int, int, int]], *, member: bool
) -> AttendanceCellOut:
    """Build the cell of one month; a month without a number counts zero."""
    present, excused, delegated = cells.get(key, (0, 0, 0))
    return AttendanceCellOut(
        month=key, member=member, present=present, excused=excused, delegated=delegated
    )


class GremienService:
    """The reads of the tab "Gremien" on one database session."""

    def __init__(self, session: AsyncSession, tz_name: str) -> None:
        """Bind the service to a session and the local time zone."""
        self.session = session
        self.tz = ZoneInfo(tz_name)

    def _today(self, now: datetime) -> _date:
        return now.astimezone(self.tz).date()

    async def overview(self, principal: Principal) -> list[GremiumOverviewOut]:
        """Return the gremien that ``principal`` sees, by name.

        A member sees the own gremien; ``gremium.view_all`` and the admin role see
        every gremium. Four queries for any number of gremien: the own roles, the
        gremien, the member counts and the next meetings, plus one for the logos.
        """
        now = datetime.now(UTC)
        own = await self._own_roles(principal)
        sees_all = views_all(principal)
        if not sees_all and (not own or not principal.scope_allows(GREMIUM_VIEW_ALL)):
            return []
        by_name = select(Gremium).order_by(Gremium.name, Gremium.id)
        stmt = by_name if sees_all else by_name.where(Gremium.id.in_(list(own)))
        gremien = tuple((await self.session.scalars(stmt)).all())
        if not gremien:
            return []
        ids = [g.id for g in gremien]
        counts = await self._member_counts(ids)
        upcoming = await self._next_meetings(ids, self._today(now))
        logos = await self._square_logos(ids)
        return [
            _overview_row(
                g,
                own.get(g.id),
                upcoming.get(g.id),
                counts.get(g.id, 0),
                has_logo=g.id in logos,
            )
            for g in gremien
        ]

    async def _own_roles(self, principal: Principal) -> dict[UUID, tuple[str, Mapping[str, str]]]:
        """Return the active roles of ``principal``: gremium → (role key, role names)."""
        rows = await self.session.execute(
            select(GremiumMembership.gremium_id, GremiumRole.key, GremiumRole.name_i18n)
            .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
            .join(PrincipalRow, PrincipalRow.id == GremiumMembership.principal_id)
            .where(
                PrincipalRow.sub == principal.sub,
                PrincipalRow.active.is_(True),
            )
        )
        return {gid: (key, dict(name or {})) for gid, key, name in rows.all()}

    async def _member_counts(self, ids: list[UUID]) -> dict[UUID, int]:
        """Return the active members per gremium: the rule of the member count of the admin page."""
        rows = await self.session.execute(
            select(
                GremiumMembership.gremium_id,
                func.count(func.distinct(GremiumMembership.principal_id)),
            )
            .join(PrincipalRow, PrincipalRow.id == GremiumMembership.principal_id)
            .where(
                GremiumMembership.gremium_id.in_(ids),
                PrincipalRow.active.is_(True),
            )
            .group_by(GremiumMembership.gremium_id)
        )
        return {gid: int(n) for gid, n in rows.all()}

    async def _next_meetings(self, ids: list[UUID], today: _date) -> dict[UUID, NextMeetingOut]:
        """Return the live meeting of each gremium, else its next planned meeting.

        A planned meeting with a date before today does not count: it did not take
        place. A planned meeting without a date comes after every dated one.
        """
        rows = await self.session.scalars(
            select(Meeting).where(
                Meeting.gremium_id.in_(ids),
                or_(
                    Meeting.status == "live",
                    and_(
                        Meeting.status == "planned",
                        or_(Meeting.date.is_(None), Meeting.date >= today),
                    ),
                ),
            )
        )
        best = {m.gremium_id: m for m in sorted(rows.all(), key=_next_rank, reverse=True)}
        return {
            gid: NextMeetingOut(
                id=m.id,
                title=m.title,
                date=m.date,
                start_time=m.start_time,
                status=m.status,  # type: ignore[arg-type]
            )
            for gid, m in best.items()
        }

    async def _square_logos(self, ids: list[UUID]) -> frozenset[UUID]:
        """Return the gremien whose CD variant has a stored raster square logo.

        The rule matches the one of the logo route (``_square_ref``).
        """
        rows = await self.session.scalars(
            select(Gremium.id)
            .join(CdVariantLogo, CdVariantLogo.variant_id == Gremium.cd_variant_id)
            .where(
                Gremium.id.in_(ids),
                CdVariantLogo.slot == SQUARE_SLOT,
                CdVariantLogo.object_key.is_not(None),
                CdVariantLogo.mime.in_(sorted(ALLOWED_SQUARE_LOGO_MIME)),
            )
            .distinct()
        )
        return frozenset(rows.all())

    async def members(
        self, gremium_id: UUID, principal: Principal, *, former: bool
    ) -> list[GremiumMemberOut]:
        """Return the members of a gremium, by role and then by name.

        A membership is active when the principal is active (the rule of the admin
        page). ``former`` gives the memberships of inactive principals.
        """
        rows = await self.session.execute(
            select(
                GremiumMembership,
                GremiumRole.key,
                GremiumRole.name_i18n,
                PrincipalRow.display_name,
                PrincipalRow.email,
                PrincipalRow.active,
                PrincipalRow.sub,
            )
            .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
            .outerjoin(PrincipalRow, PrincipalRow.id == GremiumMembership.principal_id)
            .where(GremiumMembership.gremium_id == gremium_id)
        )
        found = [
            GremiumMemberOut(
                principal_id=m.principal_id,
                display_name=display,
                email=email,
                role_id=m.gremium_role_id,
                role_key=key,
                role_name=dict(names or {}),
                is_self=sub is not None and sub == principal.sub,
            )
            for m, key, names, display, email, active, sub in rows.all()
            if bool(active) != former
        ]
        return sorted(found, key=_member_order)

    async def meetings(self, gremium_id: UUID) -> list[GremiumMeetingOut]:
        """Return the meetings of a gremium, the newest first.

        ``memberCount`` is the size of the roster of the meeting (the members of the
        gremium, plus every principal with an attendance record, see
        ``livevote.roster``); ``presentCount`` counts the ``present``
        records. Five queries for any number of meetings.
        """
        meetings = tuple(
            (
                await self.session.scalars(
                    select(Meeting)
                    .where(Meeting.gremium_id == gremium_id)
                    .order_by(
                        Meeting.date.desc().nulls_first(),
                        Meeting.start_time.desc().nulls_last(),
                        Meeting.id,
                    )
                )
            ).all()
        )
        if not meetings:
            return []
        ids = [m.id for m in meetings]
        agenda = await self.session.execute(
            select(MeetingAgendaItem.meeting_id, func.count())
            .where(MeetingAgendaItem.meeting_id.in_(ids))
            .group_by(MeetingAgendaItem.meeting_id)
        )
        items: dict[UUID, int] = {mid: int(n) for mid, n in agenda.all()}
        found = await self.session.execute(
            select(Protocol.meeting_id, Protocol.status).where(Protocol.meeting_id.in_(ids))
        )
        protocols: dict[UUID, str] = dict(found.all())
        records = await self.session.execute(
            select(
                MeetingAttendance.meeting_id,
                MeetingAttendance.principal_id,
                MeetingAttendance.status,
            ).where(MeetingAttendance.meeting_id.in_(ids))
        )
        recorded = _nested((mid, pid, status) for mid, pid, status in records.all())
        members = frozenset(
            (
                await self.session.scalars(
                    select(GremiumMembership.principal_id).where(
                        GremiumMembership.gremium_id == gremium_id
                    )
                )
            ).all()
        )
        return [
            _meeting_row(
                m, recorded.get(m.id, {}), members, items.get(m.id, 0), protocols.get(m.id)
            )
            for m in meetings
        ]

    def _closed_in(self, gremium_id: UUID, first: _date, end: _date) -> ColumnElement[bool]:
        """Return the closed meetings of a gremium with a date in ``[first, end)``."""
        return and_(
            Meeting.gremium_id == gremium_id,
            Meeting.status == "closed",
            Meeting.date >= first,
            Meeting.date < end,
        )

    async def attendance(
        self,
        gremium_id: UUID,
        principal: Principal,
        *,
        from_month: str | None,
        to_month: str | None,
    ) -> AttendanceOut:
        """Return the attendance matrix of a gremium.

        The rows are every principal with a membership in the gremium, and every
        principal with an attendance record or a vote transfer in the range.
        One SQL aggregation gives the numbers per principal and month.
        """
        now = datetime.now(UTC)
        months = month_range(from_month, to_month, self._today(now))
        first = _date(months[0][0], months[0][1], 1)
        after = shift_month(months[-1], 1)
        end = _date(after[0], after[1], 1)
        in_range = self._closed_in(gremium_id, first, end)
        month_of = func.to_char(Meeting.date, "YYYY-MM")

        held_rows = await self.session.execute(
            select(month_of, func.count()).where(in_range).group_by(month_of)
        )
        held: dict[str, int] = {str(k): int(n) for k, n in held_rows.all()}

        counts = await self.session.execute(self._attendance_counts(gremium_id, in_range))
        cells = _nested(
            (pid, str(month), (int(present), int(excused), int(delegated)))
            for pid, month, present, excused, delegated in counts.all()
        )

        terms = await self._terms(gremium_id)
        principal_ids = {t.principal_id for t in terms} | set(cells)
        people = await self._people(principal_ids)

        rows = [
            _attendance_row(
                pid,
                [t for t in terms if t.principal_id == pid],
                people.get(pid, (None, None)),
                months,
                cells.get(pid, {}),
                principal.sub,
            )
            for pid in principal_ids
        ]
        return AttendanceOut(
            from_month=month_key(months[0]),
            to_month=month_key(months[-1]),
            months=[
                AttendanceMonthOut(month=month_key(m), meetings=held.get(month_key(m), 0))
                for m in months
            ],
            rows=sorted(rows, key=_attendance_order),
        )

    def _attendance_counts(
        self, gremium_id: UUID, in_range: ColumnElement[bool]
    ) -> Select[Any, Any, Any, Any, Any]:
        """Run the one aggregation of the matrix: (principal, month, present, excused, delegated).

        The attendance records and the vote transfers go into one ``UNION ALL`` and one
        ``GROUP BY``. A record of a meeting in which the member transferred the vote is
        not an excuse; a ``present`` record of a pool substitute who is no member is not
        a member attendance.
        """
        transfer = aliased(MeetingDelegation)
        substitute = aliased(MeetingDelegation)
        month_of = func.to_char(Meeting.date, "YYYY-MM")
        transferred = exists().where(
            transfer.meeting_id == MeetingAttendance.meeting_id,
            transfer.delegator_principal_id == MeetingAttendance.principal_id,
            transfer.delegate_voting.is_(True),
        )
        pool_substitute = and_(
            exists().where(
                substitute.meeting_id == MeetingAttendance.meeting_id,
                substitute.delegate_principal_id == MeetingAttendance.principal_id,
                substitute.via_pool.is_(True),
            ),
            ~exists().where(
                GremiumMembership.gremium_id == gremium_id,
                GremiumMembership.principal_id == MeetingAttendance.principal_id,
            ),
        )
        records = (
            select(
                MeetingAttendance.principal_id.label("pid"),
                month_of.label("month"),
                case(
                    (and_(MeetingAttendance.status == "present", ~pool_substitute), 1), else_=0
                ).label("present"),
                case((and_(MeetingAttendance.status == "excused", ~transferred), 1), else_=0).label(
                    "excused"
                ),
                literal(0).label("delegated"),
            )
            .join(Meeting, Meeting.id == MeetingAttendance.meeting_id)
            .where(in_range)
        )
        transfers = (
            select(
                MeetingDelegation.delegator_principal_id.label("pid"),
                month_of.label("month"),
                literal(0).label("present"),
                literal(0).label("excused"),
                literal(1).label("delegated"),
            )
            .join(Meeting, Meeting.id == MeetingDelegation.meeting_id)
            .where(in_range, MeetingDelegation.delegate_voting.is_(True))
        )
        both = union_all(records, transfers).subquery()
        return select(
            both.c.pid,
            both.c.month,
            func.sum(both.c.present),
            func.sum(both.c.excused),
            func.sum(both.c.delegated),
        ).group_by(both.c.pid, both.c.month)

    async def _terms(self, gremium_id: UUID) -> list[_Term]:
        """Return every membership row of a gremium with its role."""
        rows = await self.session.execute(
            select(
                GremiumMembership.principal_id,
                GremiumRole.key,
                GremiumRole.name_i18n,
            )
            .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
            .where(GremiumMembership.gremium_id == gremium_id)
        )
        return [
            _Term(pid, key, dict(names or {})) for pid, key, names in rows.all()
        ]

    async def _people(self, ids: Iterable[UUID]) -> dict[UUID, tuple[str | None, str]]:
        """Return the display name and the ``sub`` of each principal."""
        wanted = list(ids)
        if not wanted:
            return {}
        rows = await self.session.execute(
            select(PrincipalRow.id, PrincipalRow.display_name, PrincipalRow.sub).where(
                PrincipalRow.id.in_(wanted)
            )
        )
        return {pid: (display, sub) for pid, display, sub in rows.all()}

    async def member_attendance(
        self, gremium_id: UUID, principal_id: UUID, month: str
    ) -> MemberAttendanceOut:
        """Return the closed meetings of one month with the state of one member.

        Raises:
            NotFoundError: The principal does not exist, or has neither a membership in
                the gremium nor a record or a vote transfer in one of its meetings
                (404 ``member_not_found``).
        """
        person = await self.session.get(PrincipalRow, principal_id)
        if person is None or not await self._related(gremium_id, principal_id):
            raise NotFoundError("member not found", code=MEMBER_NOT_FOUND)
        first_month = parse_month(month)
        after = shift_month(first_month, 1)
        found = await self.session.execute(
            select(Meeting.id, Meeting.title, Meeting.date, Meeting.start_time)
            .where(
                self._closed_in(
                    gremium_id,
                    _date(first_month[0], first_month[1], 1),
                    _date(after[0], after[1], 1),
                )
            )
            .order_by(Meeting.date, Meeting.start_time.nulls_first(), Meeting.id)
        )
        meetings = tuple(found.all())
        records, delegates = await self._member_states(
            principal_id, [mid for mid, *_ in meetings]
        )
        return MemberAttendanceOut(
            principal_id=principal_id,
            display_name=person.display_name,
            month=month_key(first_month),
            meetings=[
                MemberMeetingOut(
                    meeting_id=mid,
                    title=title,
                    date=day,
                    start_time=start,
                    status=_member_state(records.get(mid), delegated=mid in delegates),
                    delegate_name=delegates.get(mid),
                )
                for mid, title, day, start in meetings
            ],
        )

    async def _member_states(
        self, principal_id: UUID, ids: Sequence[UUID]
    ) -> tuple[dict[UUID, str], dict[UUID, str | None]]:
        """Return the records and the vote transfers of one member in some meetings.

        The first map gives the attendance status per meeting, the second the name of
        the delegate per meeting with a vote transfer. No meeting means no query.
        """
        if not ids:
            return {}, {}
        rec = await self.session.execute(
            select(MeetingAttendance.meeting_id, MeetingAttendance.status).where(
                MeetingAttendance.principal_id == principal_id,
                MeetingAttendance.meeting_id.in_(ids),
            )
        )
        records: dict[UUID, str] = dict(rec.all())
        dele = await self.session.execute(
            select(MeetingDelegation.meeting_id, PrincipalRow.display_name)
            .join(PrincipalRow, PrincipalRow.id == MeetingDelegation.delegate_principal_id)
            .where(
                MeetingDelegation.delegator_principal_id == principal_id,
                MeetingDelegation.meeting_id.in_(ids),
                MeetingDelegation.delegate_voting.is_(True),
            )
        )
        delegates: dict[UUID, str | None] = dict(dele.all())
        return records, delegates

    async def _related(self, gremium_id: UUID, principal_id: UUID) -> bool:
        """Tell if a principal has a membership, a record or a vote transfer in a gremium."""
        found = await self.session.scalar(
            select(literal(True)).where(
                or_(
                    exists().where(
                        GremiumMembership.gremium_id == gremium_id,
                        GremiumMembership.principal_id == principal_id,
                    ),
                    exists().where(
                        MeetingAttendance.principal_id == principal_id,
                        Meeting.id == MeetingAttendance.meeting_id,
                        Meeting.gremium_id == gremium_id,
                    ),
                    exists().where(
                        MeetingDelegation.gremium_id == gremium_id,
                        MeetingDelegation.delegator_principal_id == principal_id,
                    ),
                )
            )
        )
        return bool(found)

    async def decisions(
        self,
        gremium_id: UUID,
        principal: Principal,
        *,
        cursor: str | None,
        q: str | None,
        result: DecisionResultFilter | None,
        kind: DecisionKind | None,
        since: _date | None,
    ) -> DecisionPageOut:
        """Return one page of the closed votes of a gremium, the newest first.

        The votes keep the read scope of the vote list (``voting.listing.read_scope``):
        the tab never shows a vote that ``GET /votes`` hides from the caller. A result
        carries sums only, never a voter. A poll does not count, because it is no
        decision of the Gremium.
        """
        offset = decode_cursor(cursor)
        gremium_of = func.coalesce(sql_cast(Meeting.gremium_id, Text), Vote.eligible_group)
        scope = await read_scope(self.session, principal)
        since_filter: tuple[ColumnElement[bool], ...] = (
            ()
            if since is None
            else (
                Vote.closed_at
                >= datetime.combine(since, _time(0, 0), tzinfo=self.tz).astimezone(UTC),
            )
        )
        where = (
            Vote.status == "closed",
            Vote.kind != "poll",
            gremium_of == str(gremium_id),
            scope,
            self._search(q),
            *_kind_filter(kind),
            *_result_filter(result),
            *since_filter,
        )
        when = func.coalesce(Vote.closed_at, Vote.created_at)
        found = await self.session.execute(
            select(Vote, Meeting.title, Meeting.date)
            .outerjoin(Meeting, Meeting.id == Vote.meeting_id)
            .where(*where)
            .order_by(when.desc(), Vote.id.desc())
            .limit(DECISION_PAGE + 1)
            .offset(offset)
        )
        fetched = tuple(found.all())
        more = len(fetched) > DECISION_PAGE
        rows = fetched[:DECISION_PAGE]
        votes: list[Vote] = [r[0] for r in rows]
        apps = await self._applications(
            frozenset(v.application_id for v in votes if v.application_id)
        )
        sums = await self._sums([v for v in votes if not is_election(v)])
        items = [self._decision(v, title, day, apps, sums) for v, title, day in rows]
        return DecisionPageOut(
            items=items,
            next_cursor=encode_cursor(offset + DECISION_PAGE) if more else None,
        )

    @staticmethod
    def _search(q: str | None) -> ColumnElement[bool]:
        """Match the question or the meeting title; an empty query matches every vote."""
        needle = (q or "").replace("\x00", "").strip()
        if not needle:
            return true()
        like = f"%{escape_like(needle)}%"
        return or_(
            func.coalesce(Vote.question, "").ilike(like, escape="\\"),
            func.coalesce(Meeting.title, "").ilike(like, escape="\\"),
        )

    async def _applications(
        self, ids: Collection[UUID]
    ) -> dict[UUID, tuple[str | None, Decimal | None]]:
        """Return the title and the requested amount of each application."""
        if not ids:
            return {}
        rows = await self.session.execute(
            select(Application.id, Application.data, Application.amount).where(
                Application.id.in_(list(ids))
            )
        )
        return {aid: (title_of(data), amount) for aid, data, amount in rows.all()}

    async def _sums(self, votes: Sequence[Vote]) -> dict[UUID, dict[str, int]]:
        """Return the sums per option of each motion from ``secret_ballot``.

        One ``GROUP BY``; no row ever leaves the database with a voter.
        """
        if not votes:
            return {}
        rows = await self.session.execute(
            select(SecretBallot.vote_id, SecretBallot.choice, func.count())
            .where(SecretBallot.vote_id.in_([v.id for v in votes]))
            .group_by(SecretBallot.vote_id, SecretBallot.choice)
        )
        return _nested((vid, str(choice), int(n)) for vid, choice, n in rows.all())

    @staticmethod
    def _decision(
        vote: Vote,
        meeting_title: str | None,
        meeting_date: _date | None,
        apps: Mapping[UUID, tuple[str | None, Decimal | None]],
        sums: Mapping[UUID, Mapping[str, int]],
    ) -> DecisionOut:
        """Build one decision row."""
        title, amount = (
            apps.get(vote.application_id, (None, None)) if vote.application_id else (None, None)
        )
        tally = (
            _election_tally(vote)
            if is_election(vote)
            else _motion_tally(vote, sums.get(vote.id, {}))
        )
        return DecisionOut(
            id=vote.id,
            question=vote.question,
            kind=tally.kind,
            application_id=vote.application_id,
            application_title=title,
            amount=amount,
            secret=tally.secret,
            majority_rule=tally.rule,
            counts=tally.counts,
            ballots=tally.ballots,
            result=vote.result,
            elected=tally.elected,
            meeting_id=vote.meeting_id,
            meeting_title=meeting_title,
            meeting_date=meeting_date,
            closed_at=vote.closed_at,
        )
