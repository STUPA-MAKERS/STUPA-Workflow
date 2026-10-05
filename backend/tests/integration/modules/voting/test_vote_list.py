"""The vote list (``GET /votes``) against a real Postgres.

The list must show exactly the votes that ``GET /votes/{id}`` lets the caller read,
the open votes first, with the own ballot state and the agenda number of a meeting
vote.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import Gremium, GremiumMembership, GremiumRole
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.livevote.models import MeetingAgendaItem
from app.modules.voting.models import Vote
from app.modules.voting.service import VotingService
from app.shared.errors import ForbiddenError
from tests.integration.modules.voting.vote_support import (
    VoteFlow,
    add_meeting,
    add_vote,
    seed_vote_flow,
    voter,
)

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
async def session(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _member(session: AsyncSession, gremium_id: uuid.UUID, perms: list[str]) -> Principal:
    """A principal with a gremium role (no global permission, no group)."""
    row = PrincipalRow(sub=f"m-{uuid.uuid4()}", display_name="M", email="m@x.de")
    session.add(row)
    await session.flush()
    role = GremiumRole(
        gremium_id=gremium_id, key=f"r-{uuid.uuid4()}", name_i18n={"de": "R"}, permissions=perms
    )
    session.add(role)
    await session.flush()
    session.add(
        GremiumMembership(principal_id=row.id, gremium_id=gremium_id, gremium_role_id=role.id)
    )
    await session.commit()
    return Principal(sub=row.sub)


async def _other_gremium(session: AsyncSession, flow: VoteFlow) -> VoteFlow:
    """A second gremium. The test database holds one active flow, so the second
    "flow" reuses the application of the first and only changes the gremium."""
    gremium = Gremium(name="H", slug=f"h-{uuid.uuid4().hex[:8]}")
    session.add(gremium)
    await session.commit()
    return VoteFlow(
        gremium_id=gremium.id,
        app_id=flow.app_id,
        states=flow.states,
        transitions=flow.transitions,
    )


async def _set(session: AsyncSession, vote_id: uuid.UUID, **values: object) -> None:
    row = await session.get(Vote, vote_id)
    assert row is not None
    for key, value in values.items():
        setattr(row, key, value)
    await session.commit()


async def _readable(svc: VotingService, vote_id: uuid.UUID, principal: Principal) -> bool:
    try:
        await svc.get_scoped(vote_id, principal)
    except ForbiddenError:
        return False
    return True


async def test_list_matches_the_single_read(session: AsyncSession) -> None:
    mine = await seed_vote_flow(session)
    other = await _other_gremium(session, mine)
    meeting_id = await add_meeting(session, mine.gremium_id)
    first = MeetingAgendaItem(meeting_id=meeting_id, title="TOP 1", position=0)
    third = MeetingAgendaItem(meeting_id=meeting_id, title="TOP 2", position=5)
    session.add_all([first, third])
    await session.commit()

    standalone = await add_vote(session, mine, status="open", opens_at=T0)
    meeting_vote = await add_vote(
        session, mine, status="open", meeting_id=meeting_id, opens_at=T0 + timedelta(hours=1)
    )
    await _set(session, meeting_vote, agenda_item_id=third.id, question="Soll die Sitzung …?")
    closed = await add_vote(session, mine, status="closed", opens_at=T0)
    await _set(session, closed, closed_at=T0 + timedelta(days=1), result="passed")
    draft = await add_vote(session, mine, status="draft")
    foreign = await add_vote(session, other, status="open", opens_at=T0)

    svc = VotingService(session)
    # A voter of the first gremium (the vote key) who is also a member of it (the meeting).
    member = await _member(session, mine.gremium_id, ["vote.cast"])
    principal = Principal(sub=member.sub, groups=voter(member.sub, mine).groups)
    await svc.cast(standalone, principal, "yes", now=T0)

    page = await svc.list_visible(principal, limit=50, offset=0)
    ids = [item.id for item in page.items]
    # Open first (newest opened first), then the ended votes. No draft by default.
    assert ids == [meeting_vote, standalone, closed]
    assert page.total == 3
    for vote_id in (*ids, foreign):
        assert (vote_id in ids) == await _readable(svc, vote_id, principal)

    by_id = {item.id: item for item in page.items}
    assert by_id[standalone].my_ballot.cast is True
    assert by_id[standalone].my_ballot.choice == "yes"
    assert by_id[standalone].can_cast is True
    assert by_id[meeting_vote].my_ballot.cast is False
    assert by_id[meeting_vote].meeting_title == "Sitzung"
    assert by_id[meeting_vote].agenda_position == 2
    assert by_id[meeting_vote].gremium_name == "G"
    assert by_id[closed].result == "passed"

    drafts = await svc.list_visible(principal, statuses=["draft"], limit=50, offset=0)
    assert [item.id for item in drafts.items] == [draft]

    found = await svc.list_visible(principal, q="sitzung", limit=50, offset=0)
    assert [item.id for item in found.items] == [meeting_vote]
    # A `%` is a literal, not a wildcard.
    assert (await svc.list_visible(principal, q="%", limit=50, offset=0)).total == 0

    paged = await svc.list_visible(principal, limit=1, offset=1)
    assert [item.id for item in paged.items] == [standalone]
    assert paged.total == 3


async def test_gremium_filter_and_reader_scope(session: AsyncSession) -> None:
    mine = await seed_vote_flow(session)
    other = await _other_gremium(session, mine)
    a = await add_vote(session, mine, status="open", opens_at=T0)
    b = await add_vote(session, other, status="open", opens_at=T0)
    svc = VotingService(session)

    reader = Principal(sub="reader", permissions={"application.read"})
    everything = await svc.list_visible(reader, limit=200, offset=0)
    assert {a, b} <= {item.id for item in everything.items}

    only_b = await svc.list_visible(reader, gremium_id=other.gremium_id, limit=50, offset=0)
    assert [item.id for item in only_b.items] == [b]

    # A manager of the other gremium reads its standalone vote, not the first one.
    manager = await _member(session, other.gremium_id, ["vote.manage"])
    managed = await svc.list_visible(manager, limit=50, offset=0)
    assert [item.id for item in managed.items] == [b]
    assert managed.items[0].can_cast is False

    nobody = await svc.list_visible(Principal(sub="nobody"), limit=50, offset=0)
    assert nobody.items == []
    assert nobody.total == 0
