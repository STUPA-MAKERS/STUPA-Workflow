"""Load the avatar of a principal: kill switch, e-mail lookup, cache, Gravatar."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import SiteConfigVersion
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.avatars.cache import AvatarCache
from app.modules.avatars.gravatar import AvatarImage, GravatarFetcher, gravatar_hash
from app.settings import Settings


async def gravatar_enabled(db: AsyncSession) -> bool:
    """Read the admin switch ``gravatarEnabled`` of the active site config.

    Without an active config, or without the field, the switch is on.
    """
    branding = await db.scalar(
        select(SiteConfigVersion.branding).where(SiteConfigVersion.active.is_(True))
    )
    if not isinstance(branding, dict):
        return True
    return branding.get("gravatarEnabled", True) is not False


async def email_by_id(db: AsyncSession, principal_id: UUID) -> str | None:
    return await db.scalar(select(PrincipalRow.email).where(PrincipalRow.id == principal_id))


async def email_by_sub(db: AsyncSession, sub: str) -> str | None:
    return await db.scalar(select(PrincipalRow.email).where(PrincipalRow.sub == sub))


async def load_avatar(
    email: str,
    size: int,
    *,
    cache: AvatarCache,
    fetcher: GravatarFetcher,
    settings: Settings,
) -> AvatarImage | None:
    """Return the Gravatar image of ``email`` in ``size``, or ``None``.

    A cached entry wins. Otherwise the fetcher asks Gravatar, and the result goes
    into the cache: an image and a miss for ``gravatar_cache_ttl_seconds``, a failed
    fetch as a miss for the shorter ``gravatar_error_ttl_seconds``.
    """
    digest = gravatar_hash(email)
    cached = await cache.get(digest, size)
    if cached is not None:
        return cached.image
    result = await fetcher.fetch(digest, size)
    ttl = (
        settings.gravatar_error_ttl_seconds
        if result.kind == "failed"
        else settings.gravatar_cache_ttl_seconds
    )
    await cache.put(digest, size, result.image, ttl_seconds=ttl)
    return result.image
