"""Budget rollup stats: refresh of the materialized views.

``mv_budget_usage`` and ``mv_status_distribution`` are refreshed by the worker
(``CONCURRENTLY``) or non-concurrently within the same request/test.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_REFRESH_VIEWS = ("mv_budget_usage", "mv_status_distribution")


class BudgetStatsService:
    """Materialized-view refresh bound to an ``AsyncSession``."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def refresh(self, *, concurrently: bool = False) -> None:
        """Recompute both rollup materialized views.

        ``concurrently=True`` (worker) requires an AUTOCOMMIT connection plus a
        unique index per view; ``False`` runs transactionally and briefly locks
        the view.
        """
        keyword = "CONCURRENTLY " if concurrently else ""
        for view in _REFRESH_VIEWS:
            await self.session.execute(
                text(f"REFRESH MATERIALIZED VIEW {keyword}{view}")
            )
        await self.session.commit()
