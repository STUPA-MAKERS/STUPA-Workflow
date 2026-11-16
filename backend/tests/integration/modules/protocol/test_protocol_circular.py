"""A circular decision shows in the list of decisions and in no protocol (spec 000949).

Real Postgres: the protocol assembly holds no circular vote, and the list of public
decisions reads the closed circular votes of the gremien with public protocols.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.gremien.models import Gremium
from app.modules.meetings.models import Meeting, MeetingAgendaItem
from app.modules.meetings.protocol_models import Protocol
from app.modules.protocol.public import PublicFilter, PublicProtocolService
from app.modules.protocol.public_decisions import list_public_decisions
from app.modules.protocol.service import ProtocolService
from app.modules.voting.circular import circular_config
from app.modules.voting.models import SecretBallot, Vote

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 1, 17, 0, tzinfo=UTC)


@pytest.fixture
async def session(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _gremium(session: AsyncSession) -> Gremium:
    gremium = Gremium(name="AStA", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    return gremium


async def _meeting(
    session: AsyncSession, gremium: Gremium, title: str, started_at: datetime | None
) -> Meeting:
    meeting = Meeting(
        gremium_id=gremium.id,
        title=title,
        status="planned" if started_at is None else "closed",
        started_at=started_at,
    )
    session.add(meeting)
    await session.flush()
    return meeting


async def _circular(
    session: AsyncSession,
    gremium: Gremium,
    question: str,
    closed_at: datetime | None,
    *,
    status: str = "closed",
    result: str | None = "passed",
    yes: int = 0,
) -> Vote:
    vote = Vote(
        application_id=None,
        kind="circular",
        eligible_group=str(gremium.id),
        config=circular_config().model_dump(mode="json", by_alias=True),
        status=status,
        result=result,
        question=question,
        eligible_count=5,
        closed_at=closed_at,
    )
    session.add(vote)
    await session.flush()
    session.add_all(SecretBallot(vote_id=vote.id, choice="yes") for _ in range(yes))
    await session.flush()
    return vote


async def _protocol(session: AsyncSession, meeting: Meeting) -> Protocol:
    protocol = Protocol(
        meeting_id=meeting.id, gremium_id=meeting.gremium_id, markdown="", status="draft"
    )
    session.add(protocol)
    await session.commit()
    return protocol


async def test_a_protocol_lists_no_circular_vote(session: AsyncSession) -> None:
    """§F/meetings/voting/000949: no variant of a protocol holds a circular vote."""
    gremium = await _gremium(session)
    await _meeting(session, gremium, "Sitzung 1", T0)
    meeting = await _meeting(session, gremium, "Sitzung 2", T0 + timedelta(days=14))
    session.add(MeetingAgendaItem(meeting_id=meeting.id, position=1, title="Berichte"))
    await _circular(session, gremium, "Lastenanhänger beschaffen", T0 + timedelta(days=5), yes=3)
    protocol = await _protocol(session, meeting)

    svc = ProtocolService(session)
    for public in (False, True):
        document = await svc._build_document(protocol, public=public)
        assert "# Berichte" in document
        assert "Lastenanhänger" not in document
        assert "Umlaufverfahren" not in document


async def test_the_public_decisions_hold_the_circular_votes_of_a_public_gremium(
    session: AsyncSession,
) -> None:
    """§F/meetings/voting/000949: a closed circular vote of a public Gremium is public.

    The vote of a Gremium without public protocols and the vote that an objection
    cancelled stay out. The newest close comes first.
    """
    gremium = await _gremium(session)
    gremium.protocols_public = True
    internal = await _gremium(session)
    await _circular(session, gremium, "Lastenanhänger beschaffen", T0 + timedelta(days=5), yes=3)
    await _circular(
        session, gremium, "Gutachten beauftragen", T0 + timedelta(days=6), result="rejected"
    )
    await _circular(
        session, gremium, "Mit Widerspruch", T0 + timedelta(days=4), status="cancelled", result=None
    )
    await _circular(session, internal, "Internes Gremium", T0 + timedelta(days=5))
    await session.commit()

    service = PublicProtocolService(session)
    page = await list_public_decisions(service, PublicFilter(), limit=20, offset=0)
    assert [d.question for d in page.items] == [
        "Gutachten beauftragen",
        "Lastenanhänger beschaffen",
    ]
    rejected, passed = page.items
    assert (rejected.kind, rejected.result, rejected.date.isoformat()) == (
        "circular",
        "rejected",
        "2026-10-07",
    )
    assert passed.counts == {"yes": 3, "no": 0, "abstain": 0}
    assert (passed.protocol_id, passed.meeting_title) == (None, None)
    other = await list_public_decisions(
        service, PublicFilter(gremium_ids=(internal.id,)), limit=20, offset=0
    )
    assert other.items == []
