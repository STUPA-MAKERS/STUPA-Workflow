"""The feature switches in the worker (§F/administration/admin/000757).

A job of a feature that is off does not send a mail, does not fetch and does not change a
record. The retention jobs do not ask: the duties of data protection do not depend on a
switch (§F/administration/admin/000759).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.site_config.features import Feature, feature_on


async def job_feature_on(maker: async_sessionmaker[AsyncSession], feature: Feature) -> bool:
    """Return whether ``feature`` is on, read in a session of its own."""
    async with maker() as session:
        return await feature_on(session, feature)
