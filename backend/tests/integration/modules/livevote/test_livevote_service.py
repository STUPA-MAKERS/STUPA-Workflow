"""Integration test for live voting (T-16) against real Postgres and Redis.

The tests run against real infrastructure.

* MeetingService CRUD and meeting control. The schema keeps the FK
  ``vote.meeting_id → meeting.id``.
* **Cast race**: parallel casts of the same voter pass the lock and a DB ``UNIQUE``
  constraint. Exactly **one** ballot survives. See api.md section 4, acceptance
  criterion "parallel casts give 1 ballot".
* **Redis pub/sub fan-out** over **two** broker instances, which are two app instances
  on one Redis. A publish on A reaches the subscriber of B. See the acceptance
  criterion "fan-out over 2 instances".
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import date as _date
from datetime import time as _time

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import (
    ApplicationType,
    Gremium,
    GremiumMembership,
    GremiumRole,
)
from app.modules.applications.models import Application
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.flow.models import FlowVersion
from app.modules.forms.models import FormVersion
from app.modules.livevote.agenda_service import AgendaService
from app.modules.livevote.broker import RedisBroker
from app.modules.livevote.locks import RedisLocker
from app.modules.livevote.models import Meeting, MeetingAgendaItem
from app.modules.livevote.schemas import MeetingCreate, MeetingPatch
from app.modules.livevote.service import BrokerPublisher, MeetingService, meeting_channel
from app.modules.voting.models import Ballot, Vote
from app.modules.voting.service import VotingService
from app.shared.config_schemas import VoteConfig
from app.shared.errors import BadRequestError, ConflictError

pytestmark = pytest.mark.integration

_CONFIG = VoteConfig.model_validate(
    {"options": ["yes", "no"], "majorityRule": "simple", "allowChange": False}
)


@pytest.fixture
async def session(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[AsyncSession]:
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
    flow_version = FlowVersion(version=1)
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


async def _member(session: AsyncSession, gremium: Gremium) -> PrincipalRow:
    """Create an active Gremium member as a candidate protocol writer."""
    p = PrincipalRow(sub=f"s-{uuid.uuid4()}", display_name="Max P", email="m@x.de")
    session.add(p)
    await session.flush()
    role = GremiumRole(gremium_id=gremium.id, key=f"r-{uuid.uuid4()}", name_i18n={"de": "M"})
    session.add(role)
    await session.flush()
    session.add(
        GremiumMembership(
            principal_id=p.id,
            gremium_id=gremium.id,
            gremium_role_id=role.id,
            valid_from=None,
            valid_until=None,
        )
    )
    await session.flush()
    return p


async def test_meeting_crud_and_patch(session: AsyncSession) -> None:
    gremium, _ = await _gremium_and_application(session)
    member = await _member(session, gremium)
    await session.commit()
    svc = MeetingService(session)
    # An admin may control the meeting. Any other user needs a board membership.
    principal = Principal(sub="adm", roles=["admin"])
    # The create call needs a date and a start time.
    created = await svc.create(
        MeetingCreate(
            gremiumId=gremium.id,
            title="GV",
            date=_date(2026, 6, 20),
            startTime=_time(18, 0),
        ),
        principal,
    )
    assert created.status == "planned"

    fetched = await svc.get(created.id, principal)
    assert fetched.title == "GV"

    # A start without a protocol writer gives 409. The protocol needs one.
    with pytest.raises(ConflictError):
        await svc.patch(created.id, MeetingPatch(status="live"), principal)

    await svc.patch(
        created.id,
        MeetingPatch.model_validate({"protokollantId": str(member.id)}),
        principal,
    )
    patched = await svc.patch(created.id, MeetingPatch(status="live"), principal)
    assert patched.status == "live"
    assert patched.can_control is True


async def test_list_timeline_keyset_pagination(session: AsyncSession) -> None:
    """Timeline keyset: past goes backward, upcoming forward, undated last."""
    gremium, _ = await _gremium_and_application(session)
    svc = MeetingService(session)
    principal = Principal(sub="adm", roles=["admin"])

    # Direct insert: ``MeetingCreate`` now needs a date and a start time. This test also
    # needs an UNDATED meeting for the end of the sort order.
    async def mk(title: str, day: _date | None = None) -> None:
        session.add(Meeting(gremium_id=gremium.id, title=title, date=day, status="planned"))
        await session.commit()

    # Today is 2026: 2020 and 2021 are past, 2030 and 2031 upcoming, undated goes last.
    await mk("past-2020", _date(2020, 1, 1))
    await mk("past-2021", _date(2021, 6, 15))
    await mk("fut-2030", _date(2030, 1, 1))
    await mk("fut-2031", _date(2031, 1, 1))
    await mk("undated")

    # upcoming: earliest first, undated last. The cursor pages through the list.
    up: list[str] = []
    cursor: str | None = None
    while True:
        page = await svc.list_timeline(
            principal, direction="upcoming", cursor=cursor, limit=2, gremium_id=gremium.id
        )
        up.extend(m.title for m in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert up == ["fut-2030", "fut-2031", "undated"]

    # past: most recent first, going backward. Undated and upcoming meetings stay out.
    past: list[str] = []
    cursor = None
    while True:
        page = await svc.list_timeline(
            principal, direction="past", cursor=cursor, limit=1, gremium_id=gremium.id
        )
        past.extend(m.title for m in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert past == ["past-2021", "past-2020"]


async def test_list_timeline_rejects_bad_cursor(session: AsyncSession) -> None:
    svc = MeetingService(session)
    principal = Principal(sub="adm", roles=["admin"])
    with pytest.raises(BadRequestError):
        await svc.list_timeline(principal, direction="past", cursor="!!not-base64!!")


async def test_list_filter_gremien_visibility(session: AsyncSession) -> None:
    """List only the Gremien that have at least ONE visible meeting.

    `/meetings/gremien` (#meetings-filter) hides a Gremium of the member that has no
    meeting. It also hides a Gremium with a meeting where the principal is NOT a member.
    An admin sees every Gremium that has any meeting.
    """
    svc = MeetingService(session)
    g_with = Gremium(name="Mit Sitzung", slug=f"g-{uuid.uuid4()}")
    g_empty = Gremium(name="Ohne Sitzung", slug=f"g-{uuid.uuid4()}")
    g_other = Gremium(name="Fremd", slug=f"g-{uuid.uuid4()}")
    session.add_all([g_with, g_empty, g_other])
    await session.flush()

    member = await _member(session, g_with)  # member of g_with, which has a meeting
    # The same member also joins g_empty, which has NO meeting. It must NOT show up.
    role2 = GremiumRole(gremium_id=g_empty.id, key=f"r-{uuid.uuid4()}", name_i18n={"de": "M"})
    session.add(role2)
    await session.flush()
    session.add(
        GremiumMembership(
            principal_id=member.id,
            gremium_id=g_empty.id,
            gremium_role_id=role2.id,
            valid_from=None,
            valid_until=None,
        )
    )
    # One meeting in g_with (member) and one in g_other (not a member).
    session.add(Meeting(gremium_id=g_with.id, title="A", date=_date(2026, 7, 1), status="planned"))
    session.add(Meeting(gremium_id=g_other.id, title="B", date=_date(2026, 7, 2), status="planned"))
    await session.commit()

    member_principal = Principal(sub=member.sub, roles=[])
    seen = await svc.list_filter_gremien(member_principal)
    # Both g_empty (no meeting) and g_other (not a member) drop out.
    assert [g.name for g in seen] == ["Mit Sitzung"]

    admin_gremien = await svc.list_filter_gremien(Principal(sub="adm", roles=["admin"]))
    admin_seen = {g.name for g in admin_gremien}
    assert {"Mit Sitzung", "Fremd"} <= admin_seen  # every Gremium WITH a meeting
    assert "Ohne Sitzung" not in admin_seen  # never a Gremium without a meeting


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
    """Race: many parallel casts of the same voter give exactly one ballot."""
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

    # A voter needs the ``vote.cast`` permission AND the voting membership in the GREMIUM
    # (service.cast, fail-closed). The membership is the namespaced key
    # ``vote:<gremium>`` (AUD-066), which only a real vote.cast membership sets. The
    # bare UUID string does not work. Set both, or the cast gives 403.
    from app.modules.auth.rbac import vote_group_key

    principal = Principal(
        sub="alice", permissions={"vote.cast"}, groups={vote_group_key(gremium.id)}
    )
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
    """Two brokers (two app instances) on one Redis: a publish on A reaches B."""
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
            await asyncio.sleep(0.1)  # let the subscription settle before the publish
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
                assert second is False  # taken while the first holder keeps the lock
        # free again after the release
        async with locker.acquire("vote:x:cast:bob") as again:
            assert again is True
    finally:
        await client.aclose()


async def test_broker_publisher_roundtrip_over_redis(redis_url: str) -> None:
    """BrokerPublisher to RedisBroker: the aggregated vote_tally lands on the channel."""
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


async def test_agenda_set_body_renames_freetext_top_only(session: AsyncSession) -> None:
    """``set_body(title=...)`` renames free-text agenda items but never application ones."""
    gremium, application = await _gremium_and_application(session)
    meeting = Meeting(gremium_id=gremium.id, title="GV", status="planned")
    session.add(meeting)
    await session.flush()
    free = MeetingAgendaItem(
        meeting_id=meeting.id, application_id=None, title="Freitext", position=0
    )
    backed = MeetingAgendaItem(meeting_id=meeting.id, application_id=application.id, position=1)
    session.add_all([free, backed])
    await session.commit()

    svc = AgendaService(session)

    items = await svc.set_body(meeting.id, free.id, body="hello", title="Neuer Titel")
    by_id = {i.id: i for i in items}
    assert by_id[free.id].title == "Neuer Titel"
    assert by_id[free.id].body == "hello"

    # Application item: set_body ignores the title, which comes from the application.
    items = await svc.set_body(meeting.id, backed.id, body="x", title="HACK")
    refreshed = await session.get(MeetingAgendaItem, backed.id)
    assert refreshed is not None and refreshed.title is None

    # With body=None the existing body stays, but the rename still happens.
    items = await svc.set_body(meeting.id, free.id, title="Wieder anders")
    by_id = {i.id: i for i in items}
    assert by_id[free.id].title == "Wieder anders"
    assert by_id[free.id].body == "hello"


async def test_list_timeline_fuzzy_search(session: AsyncSession) -> None:
    """Fuzzy search against real Postgres: pg_trgm collapses the timeline.

    An active query merges past and upcoming into ONE list sorted by relevance with
    offset paging. The test hits the real trigram path. A typo still matches. Meetings
    out of scope and other Gremien drop out. The match comes first.
    """
    gremium = Gremium(name="Studierendenparlament", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.commit()
    svc = MeetingService(session)
    principal = Principal(sub="adm", roles=["admin"])  # an admin sees every Gremium
    for title, day in (
        ("Haushaltssitzung", _date(2026, 6, 20)),
        ("Wahlausschuss", _date(2026, 1, 10)),
        ("Klausurtagung", _date(2026, 9, 5)),
    ):
        await svc.create(
            MeetingCreate(gremiumId=gremium.id, title=title, date=day, startTime=_time(18, 0)),
            principal,
        )

    # The typo "Haushaltsitzung" with one s still gives a trigram match in one list.
    page = await svc.list_timeline(principal, direction="upcoming", q="Haushaltsitzung", limit=20)
    assert page.next_cursor is None
    assert [m.title for m in page.items] == ["Haushaltssitzung"]

    # The search joins the Gremium name and therefore finds ALL three meetings.
    by_gremium = await svc.list_timeline(
        principal, direction="upcoming", q="Studierendenparlament", limit=20
    )
    assert {m.title for m in by_gremium.items} == {
        "Haushaltssitzung",
        "Wahlausschuss",
        "Klausurtagung",
    }

    empty = await svc.list_timeline(principal, direction="upcoming", q="zzzzznope", limit=20)
    assert empty.items == [] and empty.next_cursor is None
