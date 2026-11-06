"""arq cron task: purge the expired draft uploads of the wizard.

`purge_draft_attachments` runs every hour. A draft lives until the end of its token
(`attachment_draft_token.expires_at`), which each upload moves to
`attachment_draft_ttl_days` after the upload. After that the draft can no longer be
bound, and the task removes it.

The order is fixed. The task locks a batch of drafts whose token expired, with their
token rows (`FOR UPDATE SKIP LOCKED`), collects the storage keys, deletes the rows and
commits. After the commit it removes the MinIO objects as best effort. A failed removal
leaves an orphan object and a warning, but it does not undo the purge. A second worker
skips the locked rows, and a second run finds nothing. A bound attachment has no
`draft_token_hash`, so the task never touches it. An upload in parallel that extends
the token keeps its drafts: the lock on the token row makes Postgres check the end
again on the new row version.

After the drafts the task deletes the expired draft tokens that hold no draft any
more. The foreign key of `attachment.draft_token_hash` cascades, so a token that still
held a draft would remove it without its object. Such a token, for example one whose
drafts a bind or a second worker held locked, waits for the next run.

The purge writes no audit entry. A draft never belonged to an application, and the
upload and the quarantine are already in the log.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.files.models import Attachment, AttachmentDraftToken
from app.modules.files.storage import ObjectStorage, StorageError, build_object_storage
from app.settings import load_settings

logger = logging.getLogger("app.files")

#: Rows per batch; the task loops until a batch comes back short.
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
                .join(
                    AttachmentDraftToken,
                    AttachmentDraftToken.token_hash == Attachment.draft_token_hash,
                )
                .where(
                    Attachment.application_id.is_(None),
                    AttachmentDraftToken.expires_at <= now,
                )
                .order_by(AttachmentDraftToken.expires_at)
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


async def _purge_tokens(maker: async_sessionmaker[AsyncSession], now: datetime) -> int:
    """Delete the expired draft tokens that hold no draft.

    Returns:
        The number of deleted tokens.
    """
    async with maker() as session:
        deleted = (
            await session.execute(
                delete(AttachmentDraftToken)
                .where(
                    AttachmentDraftToken.expires_at <= now,
                    ~exists().where(
                        Attachment.draft_token_hash == AttachmentDraftToken.token_hash
                    ),
                )
                .returning(AttachmentDraftToken.token_hash)
            )
        ).all()
        await session.commit()
    return len(deleted)


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
    tokens = await _purge_tokens(maker, moment)
    if purged or tokens:
        logger.info(
            "purged %d expired draft attachment(s) and %d draft token(s)", purged, tokens
        )
    return purged
