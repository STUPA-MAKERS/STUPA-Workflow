"""Integration test: finalizing a protocol needs the gremium permission (O2, O7).

The global `protocol.finalize` is gone. A principal finalizes when it has the write
access to the meeting AND its gremium role holds `protocol.finalize`. The forced roles
`vorstand` and `manager` carry the key by default. A custom role with `session.manage`
but without the key can run the meeting and write the minutes, but gets 403 on
finalize. The `canFinalize` flag of the meeting tells the frontend the same.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.gremium_roles import GremiumRoleService
from app.modules.admin.models import Gremium, GremiumMembership, GremiumRole
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.livevote.models import Meeting
from app.modules.livevote.service import MeetingService
from app.modules.protocol.models import Protocol
from app.modules.protocol.service import ProtocolService
from app.shared.errors import ForbiddenError

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _setup(session: AsyncSession) -> tuple[Gremium, Meeting, Protocol]:
    """Create a gremium with its forced roles, a closed meeting and a draft protocol."""
    gremium = Gremium(name="StuPa", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    await GremiumRoleService(session).ensure_forced_roles(gremium.id)
    meeting = Meeting(gremium_id=gremium.id, title="Sitzung", status="closed")
    session.add(meeting)
    await session.flush()
    protocol = Protocol(meeting_id=meeting.id, gremium_id=gremium.id, markdown="", status="draft")
    session.add(protocol)
    await session.commit()
    return gremium, meeting, protocol


async def _member(session: AsyncSession, gremium: Gremium, role: GremiumRole) -> Principal:
    row = PrincipalRow(sub=f"s-{uuid.uuid4()}", display_name="M", email="m@x.de")
    session.add(row)
    await session.flush()
    session.add(
        GremiumMembership(
            principal_id=row.id,
            gremium_id=gremium.id,
            gremium_role_id=role.id,
            valid_from=None,
            valid_until=None,
        )
    )
    await session.commit()
    return Principal(sub=row.sub)


async def _forced(session: AsyncSession, gremium: Gremium, key: str) -> GremiumRole:
    return (
        await session.scalars(
            select(GremiumRole).where(GremiumRole.gremium_id == gremium.id, GremiumRole.key == key)
        )
    ).one()


async def test_forced_manager_role_finalizes(session: AsyncSession) -> None:
    gremium, meeting, protocol = await _setup(session)
    manager = await _member(session, gremium, await _forced(session, gremium, "manager"))
    out = await MeetingService(session).get(meeting.id, manager)
    assert out.can_manage is True
    assert out.can_finalize is True
    await ProtocolService(session).authorize_finalize(protocol.id, manager)


async def test_forced_member_role_cannot_finalize(session: AsyncSession) -> None:
    gremium, meeting, protocol = await _setup(session)
    member = await _member(session, gremium, await _forced(session, gremium, "member"))
    out = await MeetingService(session).get(meeting.id, member)
    assert (out.can_write, out.can_finalize) == (False, False)
    with pytest.raises(ForbiddenError):
        await ProtocolService(session).authorize_finalize(protocol.id, member)


async def test_custom_session_manage_role_without_finalize_gets_403(
    session: AsyncSession,
) -> None:
    gremium, meeting, protocol = await _setup(session)
    role = GremiumRole(
        gremium_id=gremium.id,
        key="sitzungsleitung",
        name_i18n={"de": "Sitzungsleitung"},
        permissions=["session.manage", "protocol.write"],
    )
    session.add(role)
    await session.flush()
    chair = await _member(session, gremium, role)
    out = await MeetingService(session).get(meeting.id, chair)
    assert (out.can_manage, out.can_write, out.can_finalize) == (True, True, False)
    svc = ProtocolService(session)
    await svc.authorize_write(protocol.id, chair)
    with pytest.raises(ForbiddenError, match="protocol.finalize"):
        await svc.authorize_finalize(protocol.id, chair)


async def test_finalize_right_counts_only_in_its_own_gremium(session: AsyncSession) -> None:
    gremium, _, _ = await _setup(session)
    _, _, other_protocol = await _setup(session)
    board = await _member(session, gremium, await _forced(session, gremium, "vorstand"))
    with pytest.raises(ForbiddenError):
        await ProtocolService(session).authorize_finalize(other_protocol.id, board)
