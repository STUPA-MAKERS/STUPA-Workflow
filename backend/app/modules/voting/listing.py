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

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import ColumnElement, Text, and_, case, false, func, or_, select, true
from sqlalchemy import cast as sql_cast

from app.modules.admin.gremium_roles import gremium_ids_for
from app.modules.admin.models import Gremium
from app.modules.auth.rbac import VOTE_GROUP_PREFIX
from app.modules.livevote.models import Meeting, MeetingAgendaItem
from app.modules.voting.election import own_ballot
from app.modules.voting.models import Ballot, Vote, VotedMarker
from app.modules.voting.schemas import MyBallot, VoteListItem, VoteStatus
from app.search import escape_like
from app.shared.config_schemas import VoteConfig
from app.shared.paging import Page

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.auth.principal import Principal

# Without a status filter the list leaves out the drafts: a draft has no ballot yet,
# and only the managers of the vote act on it.
DEFAULT_STATUSES: tuple[VoteStatus, ...] = ("open", "closed", "cancelled")


def _gremium_text() -> ColumnElement[Any]:
    """The gremium of a vote as text: the gremium of its meeting, else its group."""
    return func.coalesce(sql_cast(Meeting.gremium_id, Text), Vote.eligible_group)


async def read_scope(session: AsyncSession, principal: Principal) -> ColumnElement[bool]:
    """Build the WHERE clause of the votes that ``principal`` can read.

    The clause mirrors ``VotingService.assert_can_read``. The query must join
    ``Meeting`` on ``Vote.meeting_id`` (outer join).
    """
    # Local import: `app.modules.livevote.service` imports the voting service.
    from app.modules.livevote.service import MeetingService

    visible, delegated = await MeetingService(session).meeting_read_scope(principal)
    if visible is None:
        meeting_ok: ColumnElement[bool] = Vote.meeting_id.is_not(None)
    else:
        meeting_ok = and_(
            Vote.meeting_id.is_not(None),
            or_(Meeting.gremium_id.in_(visible), Vote.meeting_id.in_(delegated)),
        )
    if principal.has("application.read") or principal.has("application.read_all"):
        return or_(meeting_ok, Vote.meeting_id.is_(None))
    # The eligible voter: `resolve_principal` writes `vote:<gremium>` for a gremium role
    # with `vote.cast`. The manager: `vote.manage` or `session.manage`, scope-capped.
    keys = {
        g.removeprefix(VOTE_GROUP_PREFIX)
        for g in principal.groups
        if g.startswith(VOTE_GROUP_PREFIX)
    }
    for perm in ("vote.manage", "session.manage"):
        keys |= {str(gid) for gid in await gremium_ids_for(session, principal, perm)}
    standalone_ok = (
        and_(Vote.meeting_id.is_(None), Vote.eligible_group.in_(sorted(keys)))
        if keys
        else false()
    )
    return or_(meeting_ok, standalone_ok)


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
    limit: int,
    offset: int,
) -> Page[VoteListItem]:
    """Return one page of the votes that ``principal`` can read.

    ``statuses`` defaults to ``DEFAULT_STATUSES``. ``gremium_id`` keeps the votes of
    one gremium (the gremium of the meeting, else the group of the vote). ``q``
    searches the question and the meeting title (substring, case-insensitive).
    """
    wanted = list(dict.fromkeys(statuses or DEFAULT_STATUSES))
    where = [
        Vote.status.in_(wanted),
        await read_scope(session, principal),
        _search_clause(q),
    ]
    if gremium_id is not None:
        where.append(_gremium_text() == str(gremium_id))
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
    names: dict[UUID, str] = {}
    if gremien:
        found = await session.execute(
            select(Gremium.id, Gremium.name).where(Gremium.id.in_(gremien))
        )
        names = {gid: name for gid, name in found.all()}
    positions = await _agenda_positions(session, [v for v, _, _ in rows])
    ballots = await _own_ballots(session, principal.sub, [v for v, _, _ in rows])
    voting = VotingService(session)
    items: list[VoteListItem] = []
    for vote, meeting_title, meeting_gremium in rows:
        gid = _gremium_of(vote, meeting_gremium)
        config = VoteConfig.from_stored(vote.config)
        items.append(
            VoteListItem(
                id=vote.id,
                question=vote.question,
                status=vote.status,  # type: ignore[arg-type]
                result=vote.result,  # type: ignore[arg-type]
                secret=config.secret,
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
                canCast=voting.can_cast_own(vote, principal),
                myBallot=ballots.get(vote.id, MyBallot()),
            )
        )
    return items


async def _agenda_positions(session: AsyncSession, votes: list[Vote]) -> dict[UUID, int]:
    """Return the 1-based number of each agenda item of the meetings on the page.

    The number follows `agenda_order` (position, then creation time, then id), as the
    agenda list and the meeting payload count it.
    """
    from app.modules.livevote.agenda_service import agenda_order

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

    An open vote reads the ``ballot`` row with its choice. A secret vote reads only the
    ``voted_marker``: the choice has no link to the voter.
    """
    secret = [v.id for v in votes if VoteConfig.from_stored(v.config).secret]
    plain = [v.id for v in votes if v.id not in secret]
    out: dict[UUID, MyBallot] = {}
    if plain:
        found = await session.execute(
            select(Ballot.vote_id, Ballot.choice).where(
                Ballot.voter_sub == sub, Ballot.vote_id.in_(plain)
            )
        )
        kinds = {v.id: getattr(v, "kind", "motion") for v in votes}
        out |= {
            vote_id: own_ballot(kinds[vote_id], choice) for vote_id, choice in found.all()
        }
    if secret:
        found = await session.execute(
            select(VotedMarker.vote_id).where(
                VotedMarker.voter_sub == sub, VotedMarker.vote_id.in_(secret)
            )
        )
        out |= {vote_id: MyBallot(cast=True) for vote_id in found.scalars().all()}
    return out
