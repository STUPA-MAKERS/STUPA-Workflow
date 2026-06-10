"""Budget-Rollup-Statistik (T-17, data-model §3): Refresh der materialized views.

Die nächtliche/statuswechsel-getriebene Aktualisierung der MVs ``mv_budget_usage``
und ``mv_status_distribution`` läuft per Worker (``CONCURRENTLY``) bzw. nicht-
concurrent im selben Request/Test.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_REFRESH_VIEWS = ("mv_budget_usage", "mv_status_distribution")


class BudgetStatsService:
    """MV-Refresh (an eine ``AsyncSession`` gebunden)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def refresh(self, *, concurrently: bool = False) -> None:
        """Beide Rollup-MVs neu berechnen.

        ``concurrently=True`` (Worker) erfordert eine AUTOCOMMIT-Verbindung + Unique-Index
        je MV; ``False`` (Request/Test) läuft transaktional und sperrt die MV kurz.
        """
        keyword = "CONCURRENTLY " if concurrently else ""
        for view in _REFRESH_VIEWS:
            await self.session.execute(
                text(f"REFRESH MATERIALIZED VIEW {keyword}{view}")
            )
        await self.session.commit()
