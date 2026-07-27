"""Integration test for per-Gremium protocol permissions (AUD-016, real Postgres).

Regression: the protocol write and read paths were gated on the GLOBAL
``meeting.manage``, ``protocol.finalize`` and ``meeting.view_all`` permissions. That
locked out a protocol writer assigned per Gremium. It also locked out the holder of a
Gremium role with ``protocol.write``, who may edit the agenda item bodies in the live
stack. ``resolve_principal`` keeps the Gremium role permissions out of
``principal.permissions`` on purpose. The protocol service therefore delegates to
``MeetingService`` (``can_write`` and ``assert_can_read``).

The tests run against the migrated schema.

* A member with the Gremium role ``protocol.write`` may write the protocol of ITS OWN
  meeting. The member may also read it. See ``authorize_write`` and ``authorize_read``.
* The same principal gets 403 on the protocol of a FOREIGN meeting. There is no
  cross-tenant access.
* ``authorize_finalize`` also needs ``protocol.finalize``, here through a Gremium role.
  Plain ``protocol.write`` is NOT enough.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import Gremium, GremiumMembership, GremiumRole
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.livevote.models import Meeting
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


async def _gremium_with_protocol(
    session: AsyncSession, *, role_perms: list[str]
) -> tuple[Gremium, Meeting, Protocol, PrincipalRow]:
    """Create a Gremium with a live meeting, a protocol and one member.

    The `role_perms` list holds the permissions of the Gremium role that the member
    holds.
    """
    gremium = Gremium(name="StuPa", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    member = PrincipalRow(
        sub=f"s-{uuid.uuid4()}", display_name="Pia Protokoll", email="pia@x.de"
    )
    session.add(member)
    await session.flush()
    role = GremiumRole(
        gremium_id=gremium.id,
        key=f"r-{uuid.uuid4()}",
        name_i18n={"de": "Protokollant"},
        permissions=role_perms,
    )
    session.add(role)
    await session.flush()
    session.add(
        GremiumMembership(
            principal_id=member.id,
            gremium_id=gremium.id,
            gremium_role_id=role.id,
            valid_from=None,
            valid_until=None,
        )
    )
    meeting = Meeting(gremium_id=gremium.id, title="Sitzung", status="live")
    session.add(meeting)
    await session.flush()
    protocol = Protocol(
        meeting_id=meeting.id, gremium_id=gremium.id, markdown="", status="draft"
    )
    session.add(protocol)
    await session.commit()
    return gremium, meeting, protocol, member


async def test_gremium_protocol_write_role_can_write_and_read_own(
    session: AsyncSession,
) -> None:
    _, meeting, protocol, member = await _gremium_with_protocol(
        session, role_perms=["protocol.write"]
    )
    svc = ProtocolService(session)
    principal = Principal(sub=member.sub)  # NO global permissions

    # Write and read the OWN protocol: allowed through the Gremium.
    await svc.authorize_write_meeting(meeting.id, principal)
    await svc.authorize_write(protocol.id, principal)
    await svc.authorize_read(protocol.id, principal)
    await svc.authorize_read_meeting(meeting.id, principal)


async def test_gremium_protocol_write_role_forbidden_on_other_gremium(
    session: AsyncSession,
) -> None:
    _, _, _, member = await _gremium_with_protocol(
        session, role_perms=["protocol.write"]
    )
    # A second, FOREIGN Gremium with its own protocol.
    _, other_meeting, other_protocol, _ = await _gremium_with_protocol(
        session, role_perms=["protocol.write"]
    )
    svc = ProtocolService(session)
    principal = Principal(sub=member.sub)

    with pytest.raises(ForbiddenError):
        await svc.authorize_write(other_protocol.id, principal)
    with pytest.raises(ForbiddenError):
        await svc.authorize_write_meeting(other_meeting.id, principal)
    with pytest.raises(ForbiddenError):
        await svc.authorize_read(other_protocol.id, principal)


async def test_finalize_requires_protocol_finalize_permission(
    session: AsyncSession,
) -> None:
    # Only ``protocol.write``: the member may write, but must NOT finalize.
    _, _, write_protocol, write_member = await _gremium_with_protocol(
        session, role_perms=["protocol.write"]
    )
    svc = ProtocolService(session)
    with pytest.raises(ForbiddenError):
        await svc.authorize_finalize(write_protocol.id, Principal(sub=write_member.sub))

    # A Gremium role with ``protocol.finalize`` plus write may finalize.
    _, _, fin_protocol, fin_member = await _gremium_with_protocol(
        session, role_perms=["protocol.write", "protocol.finalize"]
    )
    await svc.authorize_finalize(fin_protocol.id, Principal(sub=fin_member.sub))


async def test_global_meeting_manage_still_writes(session: AsyncSession) -> None:
    """The global ``meeting.manage`` permission (admin, org-wide) still grants write."""
    _, meeting, protocol, _ = await _gremium_with_protocol(session, role_perms=[])
    svc = ProtocolService(session)
    admin = Principal(sub="org-admin", permissions={"meeting.manage"})
    await svc.authorize_write_meeting(meeting.id, admin)
    await svc.authorize_write(protocol.id, admin)
    # Read: an org-wide holder sees everything (meeting.view_all, meeting.manage, admin).
    viewer = Principal(sub="org-view", permissions={"meeting.view_all"})
    await svc.authorize_read(protocol.id, viewer)
    # Finalize also needs protocol.finalize, even with meeting.manage.
    with pytest.raises(ForbiddenError):
        await svc.authorize_finalize(protocol.id, admin)
    finalizer = Principal(
        sub="org-fin", permissions={"meeting.manage", "protocol.finalize"}
    )
    await svc.authorize_finalize(protocol.id, finalizer)
