"""Reads of the active site configuration, for every module."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.site_config.branding import Branding
from app.modules.site_config.models import SiteConfigVersion


def branding_of(row: SiteConfigVersion | None) -> Branding:
    """Return the branding of a version row, or the defaults without a row."""
    return Branding.model_validate(row.branding) if row is not None else Branding()


async def active_branding(session: AsyncSession) -> Branding:
    """Return the active branding, or the defaults without an active version.

    Other modules read their settings from here: the ticket report reads
    ``tickets.publicEnabled``, the retention cron ``tickets.retentionMonths``.
    """
    row = (
        await session.scalars(select(SiteConfigVersion).where(SiteConfigVersion.active.is_(True)))
    ).first()
    return branding_of(row)
