"""The protocol of the next meeting lists the Umlaufverfahren (spec 000916).

Real Postgres: the protocol assembly reads the closed circular votes of the Gremium
that closed after the start of the meeting before and not after its own start.
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
from app.modules.protocol.service import ProtocolService
from app.modules.voting.circular import circular_config
from app.modules.voting.models import SecretBallot, Vote

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 1, 17, 0, tzinfo=UTC)
LEAD = "Beschlüsse im Umlaufverfahren seit der letzten Sitzung"


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


async def test_protocol_lists_the_circular_votes_since_the_meeting_before(
    session: AsyncSession,
) -> None:
    gremium = await _gremium(session)
    other = await _gremium(session)
    await _meeting(session, gremium, "Sitzung 1", T0)
    meeting = await _meeting(session, gremium, "Sitzung 2", T0 + timedelta(days=14))
    session.add(MeetingAgendaItem(meeting_id=meeting.id, position=1, title="Berichte"))
    await _circular(session, gremium, "Alter Beschluss", T0 - timedelta(days=2))
    await _circular(session, gremium, "Lastenanhänger beschaffen", T0 + timedelta(days=5), yes=3)
    await _circular(
        session, gremium, "Gutachten beauftragen", T0 + timedelta(days=6), result="rejected"
    )
    await _circular(session, gremium, "Später Beschluss", T0 + timedelta(days=15))
    await _circular(
        session, gremium, "Mit Widerspruch", T0 + timedelta(days=4), status="cancelled", result=None
    )
    await _circular(session, other, "Fremdes Gremium", T0 + timedelta(days=5))
    protocol = await _protocol(session, meeting)

    svc = ProtocolService(session)
    for public in (False, True):
        document = await svc._build_document(protocol, public=public)
        assert LEAD in document
        assert "**Lastenanhänger beschaffen**" in document
        assert "> yes: 3, no: 0, abstain: 0" in document
        assert "Umlaufverfahren · beendet am 06.10.2026 · angenommen" in document
        assert "**Gutachten beauftragen**" in document
        assert "Umlaufverfahren · beendet am 07.10.2026 · abgelehnt" in document
        assert document.index("Lastenanhänger") < document.index("Gutachten")
        assert document.index(LEAD) < document.index("# Berichte")
        for absent in ("Alter Beschluss", "Später Beschluss", "Mit Widerspruch", "Fremdes"):
            assert absent not in document


async def test_first_protocol_of_a_planned_meeting_lists_every_closed_one(
    session: AsyncSession,
) -> None:
    gremium = await _gremium(session)
    meeting = await _meeting(session, gremium, "Erste Sitzung", None)
    await _circular(session, gremium, "Früher Beschluss", T0)
    protocol = await _protocol(session, meeting)
    document = await ProtocolService(session)._build_document(protocol)
    assert LEAD in document
    assert "**Früher Beschluss**" in document


async def test_protocol_without_a_circular_vote_has_no_lead(session: AsyncSession) -> None:
    gremium = await _gremium(session)
    meeting = await _meeting(session, gremium, "Sitzung", T0)
    protocol = await _protocol(session, meeting)
    document = await ProtocolService(session)._build_document(protocol)
    assert LEAD not in document
