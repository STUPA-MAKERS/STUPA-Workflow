"""Lifecycle of magic links without a fixed scope (Z1, O3, O4, F5; real Postgres).

* A request expires no other link. Only the redeem expires the older links of the
  same application. A newer link that is not redeemed yet stays valid.
* Every link opens an edit session, also in a locked state and for an old view link.
* Archive and anonymize end every link of the application.
* The retention purge never deletes a link without an expiry.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.applications.models import Application, MagicLink
from app.modules.applications.service import ApplicationsService
from app.modules.auth import tokens
from app.modules.auth.models import ApplicantSession
from app.settings import Settings
from app.shared.errors import GoneError
from tests._support.guest_apps import (
    GuestSeed,
    create_guest_application,
    guest_settings,
    issue_magic_token,
    redeem,
    seed_guest_flow,
)
from worker import retention

pytestmark = pytest.mark.integration


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


@pytest.fixture
def settings(migrated: tuple[str, str]) -> Settings:
    return guest_settings(migrated[1])


async def _links(maker: async_sessionmaker[AsyncSession], app_id: uuid.UUID) -> list[MagicLink]:
    async with maker() as session:
        return list(
            (
                await session.scalars(
                    select(MagicLink)
                    .where(MagicLink.application_id == app_id)
                    .order_by(MagicLink.created_at)
                )
            ).all()
        )


async def _setup(
    maker: async_sessionmaker[AsyncSession],
) -> tuple[GuestSeed, uuid.UUID]:
    seed = await seed_guest_flow(maker)
    return seed, await create_guest_application(maker, seed)


async def test_redeem_expires_only_the_older_links(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    _, app_id = await _setup(maker)
    oldest = await issue_magic_token(maker, settings, app_id)
    middle = await issue_magic_token(maker, settings, app_id)
    newest = await issue_magic_token(maker, settings, app_id)
    # The requests alone expire nothing.
    assert [link.expires_at for link in await _links(maker, app_id)] == [None] * 3

    assert await redeem(maker, settings, middle) == "edit"
    first, second, third = await _links(maker, app_id)
    assert first.expires_at is not None  # older: expired by the redeem
    assert second.expires_at is None and third.expires_at is None

    with pytest.raises(GoneError):
        await redeem(maker, settings, oldest)
    # The redeemed link stays usable, and so does the newer one.
    assert await redeem(maker, settings, middle) == "edit"
    assert await redeem(maker, settings, newest) == "edit"
    # Now the newest redeem ended the middle link too.
    with pytest.raises(GoneError):
        await redeem(maker, settings, middle)


async def test_locked_state_gives_an_edit_session(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """F5: a link in a locked state opened only `view` before. Now it opens `edit`."""
    seed, app_id = await _setup(maker)
    async with maker() as session:
        await session.execute(
            update(Application)
            .where(Application.id == app_id)
            .values(current_state_id=seed.locked_state_id)
        )
        await session.commit()
    token = await issue_magic_token(maker, settings, app_id)
    (link,) = await _links(maker, app_id)
    assert link.scope == "edit" and link.single_use is False
    assert await redeem(maker, settings, token) == "edit"
    async with maker() as session:
        scopes = (
            await session.scalars(
                select(ApplicantSession.scope).where(ApplicantSession.application_id == app_id)
            )
        ).all()
    assert scopes == ["edit"]


async def test_old_view_link_opens_an_edit_session(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """O4: a single-use view link from before O3 still works once, now with edit."""
    _, app_id = await _setup(maker)
    async with maker() as session:
        session.add(
            MagicLink(
                application_id=app_id,
                token_hash=tokens.hash_token("old-view", settings.magic_link_secret),
                scope="view",
                expires_at=datetime.now(UTC) + timedelta(minutes=15),
                single_use=True,
            )
        )
        await session.commit()
    assert await redeem(maker, settings, "old-view") == "edit"
    with pytest.raises(GoneError):
        await redeem(maker, settings, "old-view")


async def test_view_link_without_expiry_violates_the_check(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    from sqlalchemy.exc import IntegrityError

    _, app_id = await _setup(maker)
    async with maker() as session:
        session.add(
            MagicLink(
                application_id=app_id,
                token_hash=b"\x01" * 32,
                scope="view",
                expires_at=None,
                single_use=True,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_archive_expires_every_link(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    _, app_id = await _setup(maker)
    token = await issue_magic_token(maker, settings, app_id)
    async with maker() as session:
        await ApplicationsService(session).set_archived(app_id, archived=True, actor="a")
    with pytest.raises(GoneError):
        await redeem(maker, settings, token)
    # Bringing it back does not revive the link.
    async with maker() as session:
        await ApplicationsService(session).set_archived(app_id, archived=False, actor="a")
    with pytest.raises(GoneError):
        await redeem(maker, settings, token)


async def test_anonymize_removes_every_link(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    _, app_id = await _setup(maker)
    token = await issue_magic_token(maker, settings, app_id)
    async with maker() as session:
        await ApplicationsService(session).anonymize(app_id)
    assert await _links(maker, app_id) == []
    with pytest.raises(GoneError):
        await redeem(maker, settings, token)


async def test_retention_purge_keeps_unlimited_links(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """A NULL `expires_at` never matches the purge. Only an ended link goes."""
    _, app_id = await _setup(maker)
    await issue_magic_token(maker, settings, app_id)
    newer = await issue_magic_token(maker, settings, app_id)
    await redeem(maker, settings, newer)  # expires the first link

    later = datetime.now(UTC) + timedelta(seconds=1)
    _, purged = await retention._purge_expired(maker, later)
    assert purged == 1
    (left,) = await _links(maker, app_id)
    assert left.expires_at is None
