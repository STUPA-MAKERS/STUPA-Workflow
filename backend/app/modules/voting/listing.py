"""The vote list (``GET /votes``): the votes that the caller can read.

The list applies the read rule of ``VotingService.assert_can_read`` in SQL:

* A meeting vote follows the meeting: the gremien of the meeting read scope
  (membership with any role, the substitute pool, ``meeting.view_all``, the admin
  role), or a meeting in which the caller receives a delegation.
* A vote without a meeting is readable with ``application.read`` or
  ``application.read_all``, for an eligible voter (the group key ``vote:<gremium>``),
  and for a holder of the gremium permission ``vote.manage`` or ``session.manage`` in
  the gremium of the vote.

The open votes come first, then the drafts, then the ended votes (closed and
cancelled). Inside each group the newest vote comes first. A row carries the own
ballot state of the caller (``myBallot``, ``canCast``) and no tally: the tally of one
vote comes from ``GET /votes/{id}``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import ColumnElement, Text, and_, case, false, func, or_, select, true
from sqlalchemy import cast as sql_cast

from app.modules.auth.policy import admin_bypass, held_gremium_ids
from app.modules.auth.rbac import VOTE_GROUP_PREFIX
from app.modules.gremien.models import Gremium
from app.modules.meetings.models import Meeting, MeetingAgendaItem
from app.modules.voting.models import Vote, VotedMarker
from app.modules.voting.schemas import MyBallot, VoteKind, VoteListItem, VoteStatus
from app.shared.config_schemas import VoteConfig
from app.shared.paging import Page
from app.shared.search import escape_like

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.auth.principal import Principal

#: Without a status filter the list leaves out the drafts: a draft has no ballot yet,
#: and only the managers of the vote act on it.
DEFAULT_STATUSES: tuple[VoteStatus, ...] = ("open", "closed", "cancelled")


def _gremium_text() -> ColumnElement[Any]:
    """The gremium of a vote as text: the gremium of its meeting, else its group."""
    return func.coalesce(sql_cast(Meeting.gremium_id, Text), Vote.eligible_group)


async def read_scope(session: AsyncSession, principal: Principal) -> ColumnElement[bool]:
    """Build the WHERE clause of the votes that ``principal`` can read.

    The clause mirrors ``VotingService.assert_can_read``. The query must join
    ``Meeting`` on ``Vote.meeting_id`` (outer join).

    The livevote import is local, because ``app.modules.livevote.service`` imports the
    voting service. A poll of a Gremium is no application vote, so the global
    application rights do not reach it, only the Gremium clause. The eligible voter
    holds ``vote:<gremium>``, which ``resolve_principal`` writes for a gremium role with
    ``vote.cast``. The manager holds ``vote.manage`` or ``session.manage``,
    scope-capped.
    """
    from app.modules.meetings.rules import MeetingRules

    visible, delegated = await MeetingRules(session).meeting_read_scope(principal)
    meeting_ok: ColumnElement[bool] = (
        Vote.meeting_id.is_not(None)
        if visible is None
        else and_(
            Vote.meeting_id.is_not(None),
            or_(Meeting.gremium_id.in_(visible), Vote.meeting_id.in_(delegated)),
        )
    )
    return (
        or_(meeting_ok, Vote.meeting_id.is_(None))
        if admin_bypass(principal, "application.read")
        else or_(meeting_ok, *await _standalone_scope(session, principal))
    )


async def _standalone_scope(
    session: AsyncSession, principal: Principal
) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    """Build the clauses of the read scope for the votes without a meeting (no admin).

    The global application rights reach the application votes. The ``vote:<gremium>``
    groups and the gremien with ``vote.manage`` or ``session.manage`` reach every vote of
    their Gremium.
    """
    global_ok: ColumnElement[bool] = (
        and_(Vote.meeting_id.is_(None), Vote.kind != "poll")
        if principal.has("application.read") or principal.has("application.read_all")
        else false()
    )
    held = [
        await held_gremium_ids(session, principal, perm)
        for perm in ("vote.manage", "session.manage")
    ]
    keys = frozenset(
        g.removeprefix(VOTE_GROUP_PREFIX)
        for g in principal.groups
        if g.startswith(VOTE_GROUP_PREFIX)
    ) | {str(gid) for ids in held for gid in ids}
    standalone_ok = (
        and_(Vote.meeting_id.is_(None), Vote.eligible_group.in_(sorted(keys)))
        if keys
        else false()
    )
    return global_ok, standalone_ok


def _search_clause(q: str | None) -> ColumnElement[bool]:
    """Match the question or the meeting title. An empty query matches every vote.

    A NUL character cannot travel to Postgres in a text parameter, so the function
    drops it.
    """
    needle = (q or "").replace("\x00", "").strip()
    if not needle:
        return true()
    like = f"%{escape_like(needle)}%"
    return or_(
        func.coalesce(Vote.question, "").ilike(like, escape="\\"),
        func.coalesce(Meeting.title, "").ilike(like, escape="\\"),
    )


async def list_votes(
    session: AsyncSession,
    principal: Principal,
    *,
    statuses: Sequence[VoteStatus] | None = None,
    gremium_id: UUID | None = None,
    q: str | None = None,
    kind: VoteKind | None = None,
    limit: int,
    offset: int,
) -> Page[VoteListItem]:
    """Return one page of the votes that ``principal`` can read.

    ``statuses`` defaults to ``DEFAULT_STATUSES``. ``gremium_id`` keeps the votes of
    one gremium (the gremium of the meeting, else the group of the vote). ``q``
    searches the question and the meeting title (substring, case-insensitive).
    ``kind`` keeps the motions, the elections or the polls.
    """
    wanted = list(dict.fromkeys(statuses or DEFAULT_STATUSES))
    where = (
        Vote.status.in_(wanted),
        await read_scope(session, principal),
        _search_clause(q),
        *((_gremium_text() == str(gremium_id),) if gremium_id is not None else ()),
        *((Vote.kind == kind,) if kind is not None else ()),
    )
    base = (
        select(Vote, Meeting.title, Meeting.gremium_id)
        .outerjoin(Meeting, Meeting.id == Vote.meeting_id)
        .where(*where)
    )
    total = await session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rank = case((Vote.status == "open", 0), (Vote.status == "draft", 1), else_=2)
    when = func.coalesce(Vote.closed_at, Vote.opens_at, Vote.created_at)
    rows = (
        await session.execute(
            base.order_by(rank, when.desc(), Vote.id.desc()).limit(limit).offset(offset)
        )
    ).all()
    items = await _decorate(session, principal, [(r[0], r[1], r[2]) for r in rows])
    return Page[VoteListItem](items=items, total=total, limit=limit, offset=offset)


def _gremium_of(vote: Vote, meeting_gremium: UUID | None) -> UUID | None:
    """The gremium of a vote: the gremium of its meeting, else its group as a UUID."""
    if meeting_gremium is not None:
        return meeting_gremium
    try:
        return UUID(vote.eligible_group)
    except (ValueError, TypeError):
        return None


async def _decorate(
    session: AsyncSession,
    principal: Principal,
    rows: list[tuple[Vote, str | None, UUID | None]],
) -> list[VoteListItem]:
    """Add the gremium names, the agenda numbers and the own ballots to the rows.

    Three queries for the whole page, not three per row.
    """
    if not rows:
        return []
    from app.modules.voting.service import VotingService

    gremien = {_gremium_of(v, g) for v, _, g in rows} - {None}
    found = (
        (
            await session.execute(select(Gremium.id, Gremium.name).where(Gremium.id.in_(gremien)))
        ).all()
        if gremien
        else ()
    )
    names: dict[UUID, str] = dict(found)
    positions = await _agenda_positions(session, [v for v, _, _ in rows])
    ballots = await _own_ballots(session, principal.sub, [v for v, _, _ in rows])
    voting = VotingService(session)
    return [
        _list_item(
            vote,
            meeting_title,
            _gremium_of(vote, meeting_gremium),
            names=names,
            positions=positions,
            ballot=ballots.get(vote.id, MyBallot()),
            can_cast=voting.can_cast_own(vote, principal),
        )
        for vote, meeting_title, meeting_gremium in rows
    ]


def _list_item(
    vote: Vote,
    meeting_title: str | None,
    gid: UUID | None,
    *,
    names: Mapping[UUID, str],
    positions: Mapping[UUID, int],
    ballot: MyBallot,
    can_cast: bool,
) -> VoteListItem:
    """Build one row of the vote list from the vote and the page lookups."""
    return VoteListItem(
        id=vote.id,
        question=vote.question,
        status=vote.status,  # type: ignore[arg-type]
        result=vote.result,  # type: ignore[arg-type]
        secret=VoteConfig.from_stored(vote.config).secret,
        kind=getattr(vote, "kind", "motion"),
        applicationId=vote.application_id,
        meetingId=vote.meeting_id,
        meetingTitle=meeting_title,
        agendaItemId=vote.agenda_item_id,
        agendaPosition=positions.get(vote.agenda_item_id) if vote.agenda_item_id else None,
        gremiumId=gid,
        gremiumName=names.get(gid) if gid is not None else None,
        createdAt=vote.created_at,
        openedAt=vote.opens_at,
        closedAt=vote.closed_at,
        closesAt=vote.closes_at,
        canCast=can_cast,
        myBallot=ballot,
    )


async def _agenda_positions(session: AsyncSession, votes: list[Vote]) -> dict[UUID, int]:
    """Return the 1-based number of each agenda item of the meetings on the page.

    The number follows `agenda_order` (position, then creation time, then id), as the
    agenda list and the meeting payload count it.
    """
    from app.modules.meetings.agenda_service import agenda_order

    meeting_ids = {v.meeting_id for v in votes if v.agenda_item_id and v.meeting_id}
    if not meeting_ids:
        return {}
    number = func.row_number().over(
        partition_by=MeetingAgendaItem.meeting_id, order_by=list(agenda_order())
    )
    found = await session.execute(
        select(MeetingAgendaItem.id, number).where(MeetingAgendaItem.meeting_id.in_(meeting_ids))
    )
    return {item_id: int(n) for item_id, n in found.all()}


async def _own_ballots(session: AsyncSession, sub: str, votes: list[Vote]) -> dict[UUID, MyBallot]:
    """Return the own ballot of ``sub`` per vote of the page.

    The method reads only the ``voted_marker``: the choice has no link to the voter.
    """
    found = await session.execute(
        select(VotedMarker.vote_id).where(
            VotedMarker.voter_sub == sub, VotedMarker.vote_id.in_([v.id for v in votes])
        )
    )
    return {vote_id: MyBallot(cast=True) for vote_id in found.scalars().all()}
