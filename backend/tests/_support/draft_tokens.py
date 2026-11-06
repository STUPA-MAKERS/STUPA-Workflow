"""Write the ``attachment_draft_token`` row that a seeded draft attachment references.

``attachment.draft_token_hash`` is a foreign key to the token row, so a test that seeds
a draft directly must write the token first. The end of the token is the end of its
drafts.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.files.models import AttachmentDraftToken


async def add_draft_token(
    session: AsyncSession, token_hash: bytes, expires_at: datetime | None = None
) -> None:
    """Insert the token row, or move its end when it exists (default: 7 days from now)."""
    end = expires_at or datetime.now(UTC) + timedelta(days=7)
    row = insert(AttachmentDraftToken).values(token_hash=token_hash, expires_at=end)
    await session.execute(
        row.on_conflict_do_update(
            index_elements=[AttachmentDraftToken.token_hash],
            set_={"expires_at": row.excluded.expires_at},
        )
    )
