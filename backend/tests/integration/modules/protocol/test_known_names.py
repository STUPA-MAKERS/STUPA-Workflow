"""Integration tests of the known names of a Sitzung (spec 000970).

The keeper reads the pairs of first and last name of the accounts, of the applicants
of the agenda and of the guests of the Sitzung. A member who cannot write a protocol
text gets 403.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.applications.models import Applicant, Application
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.flow.models import FlowVersion
from app.modules.forms.models import FormVersion
from app.modules.gremien.models import GremiumMembership, GremiumRole
from app.modules.meetings.models import Meeting, MeetingAgendaItem, MeetingGuest
from app.modules.protocol.router import get_known_names
from app.modules.protocol.schemas import KnownNameOut
from app.modules.protocol.service import ProtocolService
from app.shared.errors import ForbiddenError
from tests._support.guest_apps import seed_guest_flow

pytestmark = pytest.mark.integration


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


async def _member(session: AsyncSession, gremium_id: uuid.UUID, perms: list[str]) -> str:
    """Add a member with a Gremium role that holds the permissions; return the sub."""
    sub = f"s-{uuid.uuid4()}"
    member = PrincipalRow(sub=sub, display_name="Mira Mitglied", email=f"{sub}@x.de")
    role = GremiumRole(
        gremium_id=gremium_id,
        key=f"r-{uuid.uuid4()}",
        name_i18n={"de": "Rolle"},
        permissions=perms,
    )
    session.add_all([member, role])
    await session.flush()
    session.add(
        GremiumMembership(principal_id=member.id, gremium_id=gremium_id, gremium_role_id=role.id)
    )
    return sub


async def test_keeper_reads_the_known_names_and_a_member_does_not(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """§ 000970 An account, an applicant and a guest give pairs; a reader gets 403."""
    seed = await seed_guest_flow(maker)
    tag = uuid.uuid4().hex[:6]
    async with maker() as session:
        flow_id = (
            await session.scalars(select(FlowVersion.id).where(FlowVersion.active.is_(True)))
        ).one()
        form_id = (
            await session.scalars(
                select(FormVersion.id).where(FormVersion.application_type_id == seed.type_id)
            )
        ).first()
        assert form_id is not None
        app = Application(
            type_id=seed.type_id,
            form_version_id=form_id,
            flow_version_id=flow_id,
            current_state_id=seed.open_state_id,
            gremium_id=seed.gremium_id,
            data={"title": "Antrag"},
            lang="de",
        )
        session.add(app)
        await session.flush()
        session.add(Applicant(application_id=app.id, email="a@x.de", name=f"Anna Maria Tag{tag}"))
        session.add(PrincipalRow(sub=f"k-{tag}", display_name=f"Konto Name{tag}"))
        session.add(PrincipalRow(sub=f"o-{tag}", display_name=f"Einwort{tag}"))
        meeting = Meeting(gremium_id=seed.gremium_id, title="Sitzung", status="live")
        session.add(meeting)
        await session.flush()
        session.add(MeetingAgendaItem(meeting_id=meeting.id, application_id=app.id, position=1))
        session.add(
            MeetingGuest(
                meeting_id=meeting.id,
                seq=1,
                display_name=f"gast person{tag}",
                status="admitted",
                requested_at=datetime.now(UTC),
            )
        )
        keeper = await _member(session, seed.gremium_id, ["protocol.write"])
        reader = await _member(session, seed.gremium_id, [])
        await session.commit()
        meeting_id = meeting.id

    async with maker() as session:
        service = ProtocolService(session)
        names = await get_known_names(meeting_id, session, service, Principal(sub=keeper))
        assert KnownNameOut(first="Konto", last=f"Name{tag}") in names
        assert KnownNameOut(first="Anna", last=f"Tag{tag}") in names
        assert KnownNameOut(first="gast", last=f"person{tag}") in names
        assert all(n.last != f"Einwort{tag}" and n.first != f"Einwort{tag}" for n in names)
        with pytest.raises(ForbiddenError):
            await get_known_names(meeting_id, session, service, Principal(sub=reader))
