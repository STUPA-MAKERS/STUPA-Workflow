"""arq cron task: purge the expired draft uploads of the wizard (Z4).

`purge_draft_attachments` runs every hour. A draft lives
`attachment_draft_ttl_days` after the last upload of its token. After that it can no
longer be bound, and the task removes it.

The order is fixed. The task locks a batch of expired drafts (`FOR UPDATE SKIP
LOCKED`), deletes the rows and commits. After the commit it removes the MinIO objects
as best effort. A failed removal leaves an orphan object and a warning, but it does
not undo the purge. A second worker skips the locked rows, and a second run finds
nothing. A bound attachment has no draft columns, so the task never touches it.

The purge writes no audit entry. A draft never belonged to an application, and the
upload and the quarantine are already in the log.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.files.models import Attachment
from app.modules.files.storage import ObjectStorage, StorageError, build_object_storage
from app.settings import load_settings

logger = logging.getLogger("app.files")

# Rows per batch. The task loops until a batch comes back short.
PURGE_BATCH = 500


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """Return the DB sessionmaker (tests inject one via `ctx['files_sessionmaker']`)."""
    maker = ctx.get("files_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


def _storage(ctx: dict[str, Any]) -> ObjectStorage | None:
    """Return the object storage of the worker, or build it from the settings."""
    storage: ObjectStorage | None = ctx.get("object_storage")
    if storage is not None:
        return storage
    settings = ctx.get("settings") or load_settings()
    return build_object_storage(settings)


async def _purge_batch(
    maker: async_sessionmaker[AsyncSession], now: datetime
) -> tuple[int, list[str]]:
    """Delete one batch of expired drafts.

    Returns:
        The number of deleted rows and the storage keys of their objects.
    """
    async with maker() as session:
        rows = (
            await session.execute(
                select(Attachment.id, Attachment.storage_key)
                .where(
                    Attachment.application_id.is_(None),
                    Attachment.draft_token_hash.is_not(None),
                    Attachment.draft_expires_at <= now,
                )
                .order_by(Attachment.draft_expires_at)
                .limit(PURGE_BATCH)
                .with_for_update(skip_locked=True)
            )
        ).all()
        if not rows:
            return 0, []
        await session.execute(
            delete(Attachment).where(Attachment.id.in_([row.id for row in rows]))
        )
        await session.commit()
    return len(rows), [row.storage_key for row in rows if row.storage_key is not None]


async def _remove_objects(ctx: dict[str, Any], keys: list[str]) -> None:
    """Remove the objects of purged drafts (best effort)."""
    if not keys:
        return
    storage = _storage(ctx)
    if storage is None:
        logger.warning("no object storage: %d object(s) of purged drafts stay", len(keys))
        return
    for key in keys:
        try:
            await storage.remove(key)
        except StorageError:
            logger.warning("could not remove an object of a purged draft")


async def purge_draft_attachments(
    ctx: dict[str, Any], now: datetime | None = None
) -> int:
    """Delete the expired draft uploads and their objects.

    Returns:
        The number of purged drafts.
    """
    moment = now or datetime.now(UTC)
    maker = _sessionmaker(ctx)
    purged = 0
    while True:
        count, keys = await _purge_batch(maker, moment)
        await _remove_objects(ctx, keys)
        purged += count
        if count < PURGE_BATCH:
            break
    if purged:
        logger.info("purged %d expired draft attachment(s)", purged)
    return purged
