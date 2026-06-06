"""Integration (echte Postgres + Redis, testcontainers): Live-Vote (T-16).

Beweist gegen echte Infrastruktur:
* MeetingService-CRUD/Steuerung gegen das migrierte Schema (FK ``vote.meeting_id →
  meeting.id``).
* **Cast-Race**: parallele Stimmabgaben desselben Wählers über den Lock + DB-``UNIQUE``
  ⇒ genau **eine** Stimme (api.md §4, AK »Parallele casts → 1 Stimme«).
* **Redis-PubSub-Fan-out** über **zwei** Broker-Instanzen (= zwei App-Instanzen an
  einem Redis): publish auf A erreicht den Abonnenten von B (AK »Fan-out 2 Instanzen«).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Application
from app.modules.auth.principal import Principal
from app.modules.flow.models import FlowVersion
from app.modules.forms.models import FormVersion
from app.modules.livevote.broker import RedisBroker
from app.modules.livevote.locks import RedisLocker
from app.modules.livevote.models import Meeting
from app.modules.livevote.schemas import MeetingCreate, MeetingPatch
from app.modules.livevote.service import BrokerPublisher, MeetingService, meeting_channel
from app.modules.voting.models import Ballot, Vote
from app.modules.voting.service import VotingService
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ConflictError

pytestmark = pytest.mark.integration

_CONFIG = VoteConfig.model_validate(
    {"options": ["yes", "no"], "majorityRule": "simple", "allowChange": False}
)


@pytest.fixture
async def session(migrated: tuple[str, str]) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _gremium_and_application(session: AsyncSession) -> tuple[Gremium, Application]:
    gremium = Gremium(name="G", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    app_type = ApplicationType(
        gremium_id=gremium.id, key=f"t-{uuid.uuid4()}", name_i18n={}, has_budget=False
    )
    session.add(app_type)
    await session.flush()
    form_version = FormVersion(application_type_id=app_type.id, version=1)
    flow_version = FlowVersion(application_type_id=app_type.id, version=1)
    session.add_all([form_version, flow_version])
    await session.flush()
    application = Application(
        type_id=app_type.id,
        form_version_id=form_version.id,
        flow_version_id=flow_version.id,
    )
    session.add(application)
    await session.commit()
    return gremium, application


async def test_meeting_crud_and_patch(session: AsyncSession) -> None:
    gremium, _ = await _gremium_and_application(session)
    svc = MeetingService(session)
    created = await svc.create(
        MeetingCreate(gremiumId=gremium.id, title="GV"), Principal(sub="adm")
    )
    assert created.status == "planned"

    fetched = await svc.get(created.id)
    assert fetched.title == "GV"

    patched = await svc.patch(created.id, MeetingPatch(status="live"))
    assert patched.status == "live"


async def test_open_vote_lookup(session: AsyncSession) -> None:
    gremium, application = await _gremium_and_application(session)
    meeting = Meeting(gremium_id=gremium.id, title="GV", status="live")
    session.add(meeting)
    await session.flush()
    vote = Vote(
        application_id=application.id,
        meeting_id=meeting.id,
        eligible_group="stupa",
        config=_CONFIG.model_dump(by_alias=True),
        eligible_count=5,
        status="open",
    )
    session.add(vote)
    await session.commit()

    found = await MeetingService(session).open_vote(meeting.id)
    assert found is not None and found.id == vote.id


async def test_parallel_casts_yield_single_ballot(
    session: AsyncSession, migrated: tuple[str, str]
) -> None:
    """Race: viele gleichzeitige Casts desselben Wählers → genau 1 Stimme."""
    gremium, application = await _gremium_and_application(session)
    meeting = Meeting(gremium_id=gremium.id, title="GV", status="live")
    session.add(meeting)
    await session.flush()
    vote = Vote(
        application_id=application.id,
        meeting_id=meeting.id,
        eligible_group=str(gremium.id),
        config=_CONFIG.model_dump(by_alias=True),
        eligible_count=5,
        status="open",
    )
    session.add(vote)
    await session.commit()

    principal = Principal(sub="alice", groups={str(gremium.id)})
    from datetime import UTC, datetime

    now = datetime.now(UTC)

    async def _cast() -> str:
        eng = create_async_engine(migrated[1])
        maker = async_sessionmaker(eng, expire_on_commit=False)
        try:
            async with maker() as s:
                try:
                    await VotingService(s).cast(vote.id, principal, "yes", now=now)
                    return "ok"
                except ConflictError:
                    return "conflict"
        finally:
            await eng.dispose()

    results = await asyncio.gather(*[_cast() for _ in range(8)])
    assert results.count("ok") == 1
    assert results.count("conflict") == 7

    count = (
        await session.execute(
            select(func.count()).select_from(Ballot).where(Ballot.vote_id == vote.id)
        )
    ).scalar_one()
    assert count == 1


async def test_redis_pubsub_fanout_two_instances(redis_url: str) -> None:
    """Zwei Broker (= zwei App-Instanzen) an einem Redis: publish A → empfängt B."""
    import redis.asyncio as aioredis

    client_a = aioredis.from_url(redis_url)
    client_b = aioredis.from_url(redis_url)
    await client_a.flushdb()
    instance_a = RedisBroker(client_a)
    instance_b = RedisBroker(client_b)
    mid = uuid.uuid4()
    channel = meeting_channel(mid)

    try:
        async with instance_b.subscribe(channel) as sub_b:

            async def _first() -> dict[str, object]:
                async for msg in sub_b:
                    return msg
                raise AssertionError("no message")  # pragma: no cover

            reader = asyncio.create_task(_first())
            await asyncio.sleep(0.1)  # Abo etablieren, bevor publiziert wird
            await instance_a.publish(channel, {"type": "vote_tally", "counts": {"yes": 1}})
            received = await asyncio.wait_for(reader, timeout=5)
        assert received == {"type": "vote_tally", "counts": {"yes": 1}}
    finally:
        await client_a.aclose()
        await client_b.aclose()


async def test_redis_lock_blocks_concurrent_holder(redis_url: str) -> None:
    import redis.asyncio as aioredis

    client = aioredis.from_url(redis_url)
    await client.flushdb()
    try:
        locker = RedisLocker(client)
        async with locker.acquire("vote:x:cast:bob") as first:
            assert first is True
            async with locker.acquire("vote:x:cast:bob") as second:
                assert second is False  # belegt, solange der erste hält
        # nach Freigabe wieder erwerbbar
        async with locker.acquire("vote:x:cast:bob") as again:
            assert again is True
    finally:
        await client.aclose()


async def test_broker_publisher_roundtrip_over_redis(redis_url: str) -> None:
    """BrokerPublisher → RedisBroker: vote_tally landet aggregiert auf dem Kanal."""
    import redis.asyncio as aioredis

    from app.modules.voting.schemas import TallyOut, VoteOut

    client = aioredis.from_url(redis_url)
    await client.flushdb()
    mid, vid = uuid.uuid4(), uuid.uuid4()
    broker = RedisBroker(client)
    vote_out = VoteOut(
        id=vid,
        applicationId=uuid.uuid4(),
        meetingId=mid,
        eligibleGroup="stupa",
        config=_CONFIG,
        status="open",  # type: ignore[arg-type]
        secret=False,
        tally=TallyOut(counts={"yes": 2, "no": 0}, eligible=5, quorumMet=False),
    )
    try:
        async with broker.subscribe(meeting_channel(mid)) as sub:

            async def _first() -> dict[str, object]:
                async for msg in sub:
                    return msg
                raise AssertionError("no message")  # pragma: no cover

            reader = asyncio.create_task(_first())
            await asyncio.sleep(0.1)
            await BrokerPublisher(broker).vote_tally(vote_out)
            msg = await asyncio.wait_for(reader, timeout=5)
        assert msg["type"] == "vote_tally"
        assert msg["counts"] == {"yes": 2, "no": 0}
        assert "voter" not in msg
    finally:
        await client.aclose()
