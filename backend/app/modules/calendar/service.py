"""Calendar feed: token management plus meeting data access.

The feed token authenticates the ``.ics`` URL without a session/OIDC. Plaintext
storage is acceptable here: the token only exposes meeting titles/times of the
own gremien (low sensitivity). All functions bind to ``principal.sub`` and never
commit themselves.
"""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.gremium_roles import gremium_member_ids
from app.modules.admin.models import Gremium
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.livevote.models import Meeting

# 32 bytes -> ~43 URL-safe chars; unguessable, so no rate limit needed.
_TOKEN_BYTES = 32


def generate_calendar_token() -> str:
    """Generate a fresh unguessable feed token (URL-safe)."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


async def _row_by_sub(db: AsyncSession, sub: str) -> PrincipalRow | None:
    return (
        await db.execute(select(PrincipalRow).where(PrincipalRow.sub == sub))
    ).scalar_one_or_none()


async def get_calendar_token(db: AsyncSession, sub: str) -> str | None:
    """Read the principal's current feed token (``None`` if none generated yet)."""
    row = await _row_by_sub(db, sub)
    return row.calendar_token if row is not None else None


async def rotate_calendar_token(db: AsyncSession, sub: str) -> str | None:
    """Regenerate the feed token (old URL becomes invalid). Does not commit.

    Returns ``None`` only if the principal no longer exists.
    """
    row = await _row_by_sub(db, sub)
    if row is None:
        return None
    row.calendar_token = generate_calendar_token()
    await db.flush()
    return row.calendar_token


async def principal_by_calendar_token(
    db: AsyncSession, token: str
) -> PrincipalRow | None:
    """Resolve an active principal by feed token (or ``None``).

    Empty token or deactivated/unknown principal yields ``None``; the feed then
    answers 404 without distinguishing "wrong token" from "deactivated".
    """
    if not token:
        return None
    return (
        await db.execute(
            select(PrincipalRow).where(
                PrincipalRow.calendar_token == token,
                PrincipalRow.active.is_(True),
            )
        )
    ).scalar_one_or_none()


async def member_meetings(db: AsyncSession, sub: str) -> list[tuple[Meeting, str]]:
    """List dated meetings of the gremien ``sub`` is a member of.

    Returns ``(Meeting, gremium_name)`` pairs sorted by date/start time;
    undated meetings are skipped.
    """
    gremium_ids = await gremium_member_ids(db, sub)
    if not gremium_ids:
        return []
    rows = (
        await db.execute(
            select(Meeting, Gremium.name)
            .join(Gremium, Gremium.id == Meeting.gremium_id)
            .where(
                Meeting.gremium_id.in_(gremium_ids),
                Meeting.date.isnot(None),
            )
            .order_by(Meeting.date, Meeting.start_time)
        )
    ).all()
    return [(meeting, name) for meeting, name in rows]
