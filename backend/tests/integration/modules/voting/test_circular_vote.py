"""The Umlaufverfahren (``kind = circular``) against a real Postgres.

Specs 000914 and 000915: the create with its cast window, the fixed rules, the close
at the end of the window only, and the objection that cancels the vote.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.gremien.models import GremiumMembership, GremiumRole
from app.modules.voting.circular import CircularService
from app.modules.voting.models import Vote
from app.modules.voting.schemas import CircularCreate
from app.modules.voting.service import VotingService
from app.shared.errors import ConflictError, ForbiddenError, ValidationProblem
from tests.integration.modules.voting.vote_support import (
    VoteFlow,
    add_vote,
    audit_actions,
    seed_vote_flow,
    voter,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
END = NOW + timedelta(days=30)
ADMIN = Principal(sub="adm", roles=["admin"])


@pytest.fixture
async def session(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _members(session: AsyncSession, gremium_id: uuid.UUID, count: int) -> list[str]:
    """Add ``count`` members with ``vote.cast`` and return their subs."""
    role = GremiumRole(
        gremium_id=gremium_id,
        key=f"r-{uuid.uuid4()}",
        name_i18n={"de": "Mitglied"},
        permissions=["vote.cast", "vote.read"],
    )
    session.add(role)
    await session.flush()
    rows = [
        PrincipalRow(sub=f"c-{uuid.uuid4()}", display_name=f"M{i}", email=f"m{i}@x.de")
        for i in range(count)
    ]
    session.add_all(rows)
    await session.flush()
    session.add_all(
        GremiumMembership(principal_id=row.id, gremium_id=gremium_id, gremium_role_id=role.id)
        for row in rows
    )
    await session.commit()
    return [row.sub for row in rows]


def _body(flow: VoteFlow, **over: object) -> CircularCreate:
    data: dict[str, object] = {
        "kind": "circular",
        "eligibleGroup": str(flow.gremium_id),
        "question": "  Soll der AStA einen Lastenanhänger beschaffen?  ",
        "closesAt": END.isoformat(),
    }
    data.update(over)
    return CircularCreate.model_validate(data)


def _service(session: AsyncSession) -> CircularService:
    return CircularService(VotingService(session))


async def test_create_opens_a_circular_vote_with_the_fixed_rules(session: AsyncSession) -> None:
    flow = await seed_vote_flow(session)
    await _members(session, flow.gremium_id, 3)
    out = await _service(session).create(_body(flow), ADMIN, now=NOW)
    assert out.kind == "circular"
    assert out.status == "open"
    assert out.question == "Soll der AStA einen Lastenanhänger beschaffen?"
    assert out.meeting_id is None
    assert out.application_id is None
    assert out.config.majority_rule == "members_majority"
    assert out.config.options == ["yes", "no", "abstain"]
    assert out.config.guests_vote is False
    assert out.secret is True
    assert out.tally.eligible == 3
    assert out.closes_at == END
    assert out.cancel_reason is None
    actions = [e.action for e in await audit_actions(session, out.id)]
    assert "vote_open" in actions
    [opened] = [e for e in await audit_actions(session, out.id) if e.action == "vote_open"]
    assert opened.data["kind"] == "circular"


async def test_create_as_a_draft_and_open_later(session: AsyncSession) -> None:
    flow = await seed_vote_flow(session)
    voting = VotingService(session)
    draft = await CircularService(voting).create(_body(flow, draft=True), ADMIN, now=NOW)
    assert draft.status == "draft"
    assert draft.kind == "circular"
    opened = await voting.open(draft.id, now=NOW, actor="adm")
    assert opened.status == "open"


@pytest.mark.parametrize(
    "closes_at",
    [(NOW + timedelta(days=1)).isoformat(), "2026-12-24T12:00:00"],
)
async def test_create_with_a_short_or_naive_window_422(
    session: AsyncSession, closes_at: str
) -> None:
    flow = await seed_vote_flow(session)
    with pytest.raises(ValidationProblem) as err:
        await _service(session).create(_body(flow, closesAt=closes_at), ADMIN, now=NOW)
    assert err.value.code == "circular_window_too_short"


async def test_open_a_draft_without_an_end_422(session: AsyncSession) -> None:
    flow = await seed_vote_flow(session)
    voting = VotingService(session)
    draft = await CircularService(voting).create(_body(flow, draft=True), ADMIN, now=NOW)
    row = await session.get(Vote, draft.id)
    assert row is not None
    row.closes_at = None
    await session.commit()
    with pytest.raises(ValidationProblem) as err:
        await voting.open(draft.id, now=NOW, actor="adm")
    assert err.value.code == "circular_window_too_short"


async def test_create_in_an_unknown_gremium_422(session: AsyncSession) -> None:
    flow = await seed_vote_flow(session)
    with pytest.raises(ValidationProblem) as err:
        await _service(session).create(
            _body(flow, eligibleGroup=str(uuid.uuid4())), ADMIN, now=NOW
        )
    assert err.value.code == "eligible_group_invalid"


async def test_create_without_the_manage_right_403(session: AsyncSession) -> None:
    flow = await seed_vote_flow(session)
    with pytest.raises(ForbiddenError):
        await _service(session).create(_body(flow), voter("v1", flow), now=NOW)


async def test_close_only_at_the_end_of_the_window(session: AsyncSession) -> None:
    flow = await seed_vote_flow(session)
    subs = await _members(session, flow.gremium_id, 3)
    voting = VotingService(session)
    out = await CircularService(voting).create(_body(flow), ADMIN, now=NOW)
    for sub in subs[:2]:
        await voting.cast(out.id, voter(sub, flow), "yes", now=NOW)

    with pytest.raises(ConflictError) as err:
        await voting.close(out.id, ADMIN)
    assert err.value.code == "circular_window_open"

    closed = await voting.close(out.id, ADMIN, now=END)
    assert closed.result == "passed"
    assert closed.branch_fired is False
    read = await voting.get(out.id)
    assert read.status == "closed"
    assert read.kind == "circular"
    assert read.tally.counts == {"yes": 2, "no": 0, "abstain": 0}


async def test_a_minority_of_the_members_does_not_pass(session: AsyncSession) -> None:
    flow = await seed_vote_flow(session)
    subs = await _members(session, flow.gremium_id, 4)
    voting = VotingService(session)
    out = await CircularService(voting).create(_body(flow), ADMIN, now=NOW)
    for sub in subs[:2]:
        await voting.cast(out.id, voter(sub, flow), "yes", now=NOW)
    closed = await voting.close(out.id, ADMIN, now=END)
    assert closed.result == "rejected"


async def test_manual_close_after_the_end_and_without_an_end(session: AsyncSession) -> None:
    flow = await seed_vote_flow(session)
    voting = VotingService(session)
    out = await CircularService(voting).create(_body(flow), ADMIN, now=NOW)
    row = await session.get(Vote, out.id)
    assert row is not None
    row.closes_at = None
    await session.commit()
    with pytest.raises(ConflictError) as err:
        await voting.close(out.id, ADMIN)
    assert err.value.code == "circular_window_open"

    row.closes_at = datetime.now(UTC) - timedelta(minutes=1)
    await session.commit()
    closed = await voting.close(out.id, ADMIN)
    assert closed.result == "rejected"


async def test_an_objection_cancels_the_vote(session: AsyncSession) -> None:
    flow = await seed_vote_flow(session)
    [sub] = await _members(session, flow.gremium_id, 1)
    service = _service(session)
    out = await service.create(_body(flow), ADMIN, now=NOW)

    with pytest.raises(ForbiddenError):
        await service.object(out.id, Principal(sub="outsider"), now=NOW)

    cancelled = await service.object(out.id, voter(sub, flow), now=NOW)
    assert cancelled.status == "cancelled"
    assert cancelled.cancel_reason == "objection"
    assert cancelled.result is None
    [entry] = [e for e in await audit_actions(session, out.id) if e.action == "vote_cancel"]
    assert entry.actor == sub
    assert entry.data["reason"] == "objection"
    assert entry.data["previousStatus"] == "open"

    with pytest.raises(ConflictError) as err:
        await service.object(out.id, voter(sub, flow), now=NOW)
    assert err.value.code == "vote_not_open"


async def test_an_objection_needs_a_circular_vote(session: AsyncSession) -> None:
    flow = await seed_vote_flow(session)
    motion = await add_vote(session, flow)
    with pytest.raises(ConflictError) as err:
        await _service(session).object(motion, voter("v1", flow), now=NOW)
    assert err.value.code == "not_circular"


async def test_only_the_gremium_reads_and_manages_a_circular_vote(session: AsyncSession) -> None:
    flow = await seed_vote_flow(session)
    [sub] = await _members(session, flow.gremium_id, 1)
    voting = VotingService(session)
    out = await CircularService(voting).create(_body(flow), ADMIN, now=NOW)

    member = await voting.get_scoped(out.id, voter(sub, flow))
    assert member.can_cast is True
    assert member.can_manage is False
    admin = await voting.get_scoped(out.id, ADMIN)
    assert admin.can_manage is True
    reader = Principal(sub="reader", permissions={"application.read", "application.read_all"})
    with pytest.raises(ForbiddenError):
        await voting.get_scoped(out.id, reader)
