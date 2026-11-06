"""The hourly cron purges expired draft uploads with their objects (real Postgres).

* An expired draft goes: the row and the MinIO object.
* A draft that has not expired stays, and so does a bound attachment.
* The purge works in batches until a batch comes back short.
* A second run finds nothing.
* An expired draft token goes, a live one stays.
* A token that still holds a draft stays, so the cascade never drops a draft whose
  object the purge did not collect.

Each draft gets its own token here, because the end of the token is the end of the
draft.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.files.models import Attachment, AttachmentDraftToken
from tests._support.guest_apps import create_guest_application, seed_guest_flow
from worker import files_drafts as wfd

pytestmark = pytest.mark.integration


class _Storage:
    """Object storage fake that records the removed keys."""

    def __init__(self) -> None:
        self.removed: list[str] = []

    async def remove(self, key: str) -> None:
        self.removed.append(key)


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


def _draft(
    expires_at: datetime, *, key: str | None = "auto"
) -> tuple[AttachmentDraftToken, Attachment]:
    """Return a token that ends at ``expires_at`` and one draft of it."""
    aid = uuid.uuid4()
    token = AttachmentDraftToken(token_hash=uuid.uuid4().bytes * 2, expires_at=expires_at)
    draft = Attachment(
        id=aid,
        application_id=None,
        filename="d.pdf",
        mime="application/pdf",
        size=1,
        storage_key=f"drafts/{aid}/d.pdf" if key == "auto" else key,
        draft_token_hash=token.token_hash,
    )
    return token, draft


async def _add(
    maker: async_sessionmaker[AsyncSession], pairs: list[tuple[AttachmentDraftToken, Attachment]]
) -> None:
    """Write the tokens first, because each draft references its token."""
    async with maker() as session:
        session.add_all([token for token, _ in pairs])
        await session.flush()
        session.add_all([draft for _, draft in pairs])
        await session.commit()


async def test_purge_removes_expired_drafts_only(
    maker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Purge the expired drafts only.

    An infected draft has no object any more, but its row goes all the same. Small batches
    prove the loop.
    """
    now = datetime.now(UTC)
    seed = await seed_guest_flow(maker)
    app_id = await create_guest_application(maker, seed)
    expired_pairs = [_draft(now - timedelta(minutes=i + 1)) for i in range(5)]
    infected_pair = _draft(now - timedelta(hours=1), key=None)
    alive_pair = _draft(now + timedelta(days=1))
    await _add(maker, [*expired_pairs, infected_pair, alive_pair])
    expired = [draft for _, draft in expired_pairs]
    alive = alive_pair[1]
    bound = Attachment(
        application_id=app_id,
        filename="b.pdf",
        mime="application/pdf",
        size=1,
        storage_key=f"{app_id}/x/b.pdf",
    )
    async with maker() as session:
        session.add(bound)
        await session.commit()

    monkeypatch.setattr(wfd, "PURGE_BATCH", 2)
    storage = _Storage()
    ctx = {"files_sessionmaker": maker, "object_storage": storage}
    assert await wfd.purge_draft_attachments(ctx, now=now) == 6
    assert sorted(storage.removed) == sorted(str(a.storage_key) for a in expired)

    async with maker() as session:
        left = set((await session.scalars(select(Attachment.id))).all())
    assert left == {alive.id, bound.id}
    async with maker() as session:
        tokens = set((await session.scalars(select(AttachmentDraftToken.token_hash))).all())
    assert tokens == {alive_pair[0].token_hash}

    assert await wfd.purge_draft_attachments(ctx, now=now) == 0


async def test_token_purge_keeps_a_token_that_still_holds_a_draft(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """The token purge alone never cascades onto a draft."""
    now = datetime.now(UTC)
    token, draft = _draft(now - timedelta(minutes=1))
    await _add(maker, [(token, draft)])
    assert await wfd._purge_tokens(maker, now) == 0
    async with maker() as session:
        assert await session.get(Attachment, draft.id) is not None
        assert await session.get(AttachmentDraftToken, token.token_hash) is not None


async def test_purge_removes_expired_tokens_only(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    async with maker() as session:
        session.add_all(
            [
                AttachmentDraftToken(token_hash=b"\x02" * 32, expires_at=now),
                AttachmentDraftToken(
                    token_hash=b"\x03" * 32, expires_at=now - timedelta(days=1)
                ),
                AttachmentDraftToken(
                    token_hash=b"\x04" * 32, expires_at=now + timedelta(minutes=1)
                ),
            ]
        )
        await session.commit()

    ctx = {"files_sessionmaker": maker, "object_storage": _Storage()}
    assert await wfd.purge_draft_attachments(ctx, now=now) == 0

    async with maker() as session:
        left = set((await session.scalars(select(AttachmentDraftToken.token_hash))).all())
    assert left == {b"\x04" * 32}
