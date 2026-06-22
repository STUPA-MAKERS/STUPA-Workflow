"""Integration (echte Postgres): per-Gremium-Protokoll-Berechtigung (AUD-016).

Regression: Protokoll-Schreiben/Lesen war auf GLOBALE ``meeting.manage``/
``protocol.finalize``/``meeting.view_all`` gegatet — das sperrte einen per-Gremium
zugewiesenen Protokollanten bzw. einen Inhaber einer Gremium-Rolle mit
``protocol.write`` aus, obwohl er die TOP-Bodies (Live-Stack) editieren darf.
``resolve_principal`` führt Gremium-Rollen-Permissions absichtlich NICHT in
``principal.permissions``; der Protokoll-Service delegiert deshalb an
``MeetingService`` (``can_write``/``assert_can_read``).

Beweist gegen das migrierte Schema:
* ein Mitglied mit Gremium-Rolle ``protocol.write`` darf das Protokoll SEINER Sitzung
  schreiben (``authorize_write``) und lesen (``authorize_read``);
* derselbe Principal ist auf das Protokoll einer FREMDEN Sitzung 403 (kein
  Cross-Tenant-Zugriff);
* ``authorize_finalize`` verlangt zusätzlich ``protocol.finalize`` (hier per
  Gremium-Rolle) — reines ``protocol.write`` reicht NICHT.
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
    """Gremium + live-Sitzung + Protokoll + Mitglied mit Gremium-Rolle ``role_perms``."""
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
    principal = Principal(sub=member.sub)  # KEINE globalen Permissions

    # Schreiben + Lesen des EIGENEN Protokolls: erlaubt (per Gremium).
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
    # Zweites, FREMDES Gremium mit eigenem Protokoll.
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
    # Nur ``protocol.write`` → darf schreiben, aber NICHT finalisieren.
    _, _, write_protocol, write_member = await _gremium_with_protocol(
        session, role_perms=["protocol.write"]
    )
    svc = ProtocolService(session)
    with pytest.raises(ForbiddenError):
        await svc.authorize_finalize(write_protocol.id, Principal(sub=write_member.sub))

    # Gremium-Rolle mit ``protocol.finalize`` (+ write) → darf finalisieren.
    _, _, fin_protocol, fin_member = await _gremium_with_protocol(
        session, role_perms=["protocol.write", "protocol.finalize"]
    )
    await svc.authorize_finalize(fin_protocol.id, Principal(sub=fin_member.sub))


async def test_global_meeting_manage_still_writes(session: AsyncSession) -> None:
    """Globale ``meeting.manage`` (Admin/org-weit) bleibt unverändert berechtigt."""
    _, meeting, protocol, _ = await _gremium_with_protocol(session, role_perms=[])
    svc = ProtocolService(session)
    admin = Principal(sub="org-admin", permissions={"meeting.manage"})
    await svc.authorize_write_meeting(meeting.id, admin)
    await svc.authorize_write(protocol.id, admin)
    # Lesen: org-weite Inhaber sehen alles (meeting.view_all/meeting.manage/Admin).
    viewer = Principal(sub="org-view", permissions={"meeting.view_all"})
    await svc.authorize_read(protocol.id, viewer)
    # Finalisieren verlangt zusätzlich protocol.finalize (auch für meeting.manage).
    with pytest.raises(ForbiddenError):
        await svc.authorize_finalize(protocol.id, admin)
    finalizer = Principal(
        sub="org-fin", permissions={"meeting.manage", "protocol.finalize"}
    )
    await svc.authorize_finalize(protocol.id, finalizer)
