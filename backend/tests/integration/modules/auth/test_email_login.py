"""The e-mail login of the applicants (real Postgres).

* A link goes out only for an address with an Antrag, and it opens the list page
  (F/administration/accounts/000583).
* An account address gets a link and an applicant session only
  (F/administration/accounts/000584).
* A link works once and ends with its time (F/administration/accounts/000585).
* The first redeem confirms every waiting guest Antrag of the address
  (F/administration/accounts/000586).
* A confirmed guest Antrag of an account address belongs to the account, not before
  (F/administration/accounts/000587).
* The session reads its Anträge at each request (NF/security/access/000590).
* The retention purge deletes a used or ended link.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.applications.models import Application
from app.modules.applications.service import ApplicationsService
from app.modules.audit.actions import AuditAction
from app.modules.audit.models import AuditEntry
from app.modules.auth import email_login
from app.modules.auth.models import ApplicantSession, EmailLoginLink
from app.modules.auth.models import Principal as PrincipalRow
from app.settings import Settings
from app.shared.errors import GoneError
from tests._support.guest_apps import (
    GUEST_EMAIL,
    GuestSeed,
    create_guest_application,
    guest_settings,
    issue_magic_token,
    redeem,
    seed_guest_flow,
)
from tests.integration.conftest import clear_privacy_tables
from worker import retention

pytestmark = pytest.mark.integration


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    clear_privacy_tables(engine)
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()
    clear_privacy_tables(engine)


@pytest.fixture
def settings(migrated: tuple[str, str]) -> Settings:
    return guest_settings(migrated[1])


def _token(link: str) -> str:
    match = re.search(r"/my-applications#t=(.+)$", link)
    assert match is not None
    return match.group(1)


async def _request(
    maker: async_sessionmaker[AsyncSession], settings: Settings, email: str
) -> list[str]:
    sent: list[str] = []

    def send(_email: str, link: str) -> None:
        sent.append(link)

    async with maker() as session:
        await email_login.request_email_login(session, settings, email=email, send_link=send)
        await session.commit()
    return sent


async def _verify(
    maker: async_sessionmaker[AsyncSession], settings: Settings, token: str
) -> str:
    async with maker() as session:
        sid = await email_login.verify_email_login(session, settings, token=token)
        await session.commit()
    return sid


async def _confirmed(maker: async_sessionmaker[AsyncSession], app_id: uuid.UUID) -> bool:
    async with maker() as session:
        app = await session.get(Application, app_id)
        assert app is not None
        return app.email_confirmed_at is not None


async def _owner(maker: async_sessionmaker[AsyncSession], app_id: uuid.UUID) -> str | None:
    async with maker() as session:
        app = await session.get(Application, app_id)
        assert app is not None
        return app.created_by


async def _account(
    maker: async_sessionmaker[AsyncSession],
    email: str,
    *,
    active: bool = True,
    last_login: datetime | None = None,
) -> PrincipalRow:
    async with maker() as session:
        row = PrincipalRow(
            sub=f"sub-{uuid.uuid4().hex[:8]}", email=email, active=active, last_login=last_login
        )
        session.add(row)
        await session.commit()
        return row


async def _setup(maker: async_sessionmaker[AsyncSession]) -> tuple[GuestSeed, uuid.UUID]:
    seed = await seed_guest_flow(maker)
    return seed, await create_guest_application(maker, seed)


async def test_link_only_for_an_address_with_an_antrag(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """An unknown address gets nothing; a known one, in any case, gets one link."""
    await _setup(maker)
    assert await _request(maker, settings, "niemand@example.org") == []
    (link,) = await _request(maker, settings, GUEST_EMAIL.upper())
    assert link.startswith(settings.public_base_url.rstrip("/") + "/my-applications#t=")


async def test_redeem_opens_an_email_session_and_confirms_every_waiting_antrag(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """One redeem confirms both waiting Anträge of the address, not the other one."""
    seed, first = await _setup(maker)
    second = await create_guest_application(maker, seed)
    other = await create_guest_application(maker, seed, "andere@example.org")
    (link,) = await _request(maker, settings, GUEST_EMAIL)

    assert await _verify(maker, settings, _token(link))
    assert await _confirmed(maker, first)
    assert await _confirmed(maker, second)
    assert not await _confirmed(maker, other)
    async with maker() as session:
        rows = list(await session.scalars(select(ApplicantSession)))
    assert [(r.email, r.application_id) for r in rows] == [(GUEST_EMAIL, None)]


async def test_a_link_works_once(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """A second redeem of the same link is gone; a second request does not end the first."""
    await _setup(maker)
    (first,) = await _request(maker, settings, GUEST_EMAIL)
    (second,) = await _request(maker, settings, GUEST_EMAIL)
    await _verify(maker, settings, _token(first))
    with pytest.raises(GoneError):
        await _verify(maker, settings, _token(first))
    await _verify(maker, settings, _token(second))


async def test_a_link_ends_after_its_time(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """A link from the login page ends after 30 minutes; an unknown token is gone."""
    await _setup(maker)
    (link,) = await _request(maker, settings, GUEST_EMAIL)
    async with maker() as session:
        (row,) = await session.scalars(select(EmailLoginLink))
        assert row.expires_at - row.created_at <= email_login.LINK_TTL + timedelta(seconds=5)
        await session.execute(
            update(EmailLoginLink).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    with pytest.raises(GoneError):
        await _verify(maker, settings, _token(link))
    with pytest.raises(GoneError):
        await _verify(maker, settings, "unbekannt")


async def test_the_confirm_link_ends_with_the_confirmation_window(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """The link of the mail after a new Antrag lives as long as the confirmation window."""
    await _setup(maker)
    async with maker() as session:
        link = await email_login.issue_confirm_link(session, settings, email=GUEST_EMAIL)
        await session.commit()
        (row,) = await session.scalars(select(EmailLoginLink))
    window = row.expires_at - datetime.now(UTC)
    assert timedelta(hours=11, minutes=59) < window <= timedelta(hours=12)
    assert await _verify(maker, settings, _token(link))


async def test_an_account_address_gets_an_applicant_session_only(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """The address of an account gets a link, and the session has no principal."""
    await _setup(maker)
    await _account(maker, GUEST_EMAIL)
    (link,) = await _request(maker, settings, GUEST_EMAIL)
    await _verify(maker, settings, _token(link))
    async with maker() as session:
        applicant = await email_login.resolve_session(session, GUEST_EMAIL)
    assert applicant.email == GUEST_EMAIL
    assert not hasattr(applicant, "sub")


async def test_a_confirmed_antrag_belongs_to_the_account_only_after_the_redeem(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """Before the redeem the Antrag has no owner; after it the newest active login owns it."""
    _, app_id = await _setup(maker)
    await _account(maker, GUEST_EMAIL, last_login=datetime(2026, 1, 1, tzinfo=UTC))
    newest = await _account(maker, GUEST_EMAIL, last_login=datetime(2026, 6, 1, tzinfo=UTC))
    await _account(maker, GUEST_EMAIL, active=False, last_login=datetime(2026, 9, 1, tzinfo=UTC))
    assert await _owner(maker, app_id) is None

    (link,) = await _request(maker, settings, GUEST_EMAIL)
    await _verify(maker, settings, _token(link))
    assert await _owner(maker, app_id) == newest.sub
    async with maker() as session:
        (entry,) = await session.scalars(
            select(AuditEntry).where(
                AuditEntry.action == AuditAction.APPLICATION_OWNER_MATCH.value
            )
        )
    assert entry.target_id == str(app_id)
    assert entry.data == {"principalId": str(newest.id), "matchedByEmail": True}


async def test_an_old_link_of_one_antrag_also_assigns_the_account(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """The confirmation by an old link of one Antrag gives it to the account too."""
    _, app_id = await _setup(maker)
    account = await _account(maker, GUEST_EMAIL)
    token = await issue_magic_token(maker, settings, app_id)
    await redeem(maker, settings, token)
    assert await _owner(maker, app_id) == account.sub


async def test_the_session_reads_its_antraege_at_each_request(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """A new Antrag joins and an anonymized one drops out."""
    seed, first = await _setup(maker)
    async with maker() as session:
        assert (await email_login.resolve_session(session, GUEST_EMAIL)).application_ids == {
            str(first)
        }
    second = await create_guest_application(maker, seed)
    async with maker() as session:
        await ApplicationsService(session).anonymize(first, actor="test")
        await session.commit()
    async with maker() as session:
        ids = (await email_login.resolve_session(session, GUEST_EMAIL)).application_ids
    assert ids == {str(second)}


async def test_retention_purges_used_and_ended_links(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """The purge deletes a used and an ended link and keeps a valid one."""
    await _setup(maker)
    (used,) = await _request(maker, settings, GUEST_EMAIL)
    await _verify(maker, settings, _token(used))
    await _request(maker, settings, GUEST_EMAIL)
    await _request(maker, settings, GUEST_EMAIL)
    async with maker() as session:
        open_links = select(EmailLoginLink).where(EmailLoginLink.used_at.is_(None))
        rows = list(await session.scalars(open_links.order_by(EmailLoginLink.created_at)))
        await session.execute(
            update(EmailLoginLink)
            .where(EmailLoginLink.id == rows[0].id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    await retention._purge_expired(maker, datetime.now(UTC))
    async with maker() as session:
        left = list(await session.scalars(select(EmailLoginLink)))
    assert [row.id for row in left] == [rows[1].id]
