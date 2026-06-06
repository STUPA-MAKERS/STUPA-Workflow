"""Budget-Rollup-Statistik (T-17, data-model §3): materialized views + Refresh.

Liest die MVs ``mv_budget_usage`` (Topf × Stufe, Summen) und ``mv_status_distribution``
(Gremium × State, Zähler) und baut daraus die ``/budget/stats``-Antwort. Der Refresh
läuft per Worker (``CONCURRENTLY``, nächtlicher Cron + bei Statuswechsel) bzw. nicht-
concurrent im selben Request/Test. Aggregations-Logik ist rein (``rules``).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import column, select, table, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.budget import rules
from app.modules.budget.models import BudgetPot
from app.modules.budget.schemas import BudgetStatsOut, PotUsageOut, StatusBucketOut

# Leichte selectables auf die MVs (nicht in Base.metadata → kein create_all/Autogenerate).
_mv_usage = table(
    "mv_budget_usage",
    column("budget_pot_id"),
    column("stage"),
    column("total_amount"),
)
_mv_status = table(
    "mv_status_distribution",
    column("gremium_id"),
    column("current_state_id"),
    column("application_count"),
)

_REFRESH_VIEWS = ("mv_budget_usage", "mv_status_distribution")


class BudgetStatsService:
    """MV-gestützte Statistik (an eine ``AsyncSession`` gebunden)."""

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

    async def usage(
        self,
        *,
        gremium_id: UUID | None = None,
        period: str | None = None,
        budget_pot_id: UUID | None = None,
    ) -> list[PotUsageOut]:
        """Auslastung je Topf (gefiltert). Töpfe ohne Entries erscheinen mit Null-Summen."""
        pot_filters = []
        if gremium_id is not None:
            pot_filters.append(BudgetPot.gremium_id == gremium_id)
        if period is not None:
            pot_filters.append(BudgetPot.period == period)
        if budget_pot_id is not None:
            pot_filters.append(BudgetPot.id == budget_pot_id)
        pots = (
            await self.session.execute(
                select(BudgetPot).where(*pot_filters).order_by(BudgetPot.name)
            )
        ).scalars().all()

        usage_stmt = select(
            _mv_usage.c.budget_pot_id, _mv_usage.c.stage, _mv_usage.c.total_amount
        )
        if budget_pot_id is not None:
            usage_stmt = usage_stmt.where(_mv_usage.c.budget_pot_id == budget_pot_id)
        usage_rows = (await self.session.execute(usage_stmt)).all()
        by_pot = rules.stage_sums_by_pot(
            (r.budget_pot_id, r.stage, _as_decimal(r.total_amount)) for r in usage_rows
        )

        out: list[PotUsageOut] = []
        for pot in pots:
            usage = rules.usage_from_stage_sums(by_pot.get(pot.id, {}), pot.total)
            out.append(
                PotUsageOut(
                    budgetPotId=pot.id,
                    period=pot.period,
                    total=pot.total,
                    currency=pot.currency,
                    requested=usage.requested,
                    reserved=usage.reserved,
                    approved=usage.approved,
                    paid=usage.paid,
                    committed=usage.committed,
                    available=usage.available,
                )
            )
        return out

    async def status_distribution(
        self, *, gremium_id: UUID | None = None
    ) -> list[StatusBucketOut]:
        """Statusverteilung (Gremium × State, Zähler)."""
        stmt = select(
            _mv_status.c.gremium_id,
            _mv_status.c.current_state_id,
            _mv_status.c.application_count,
        )
        if gremium_id is not None:
            stmt = stmt.where(_mv_status.c.gremium_id == gremium_id)
        rows = (await self.session.execute(stmt)).all()
        return [
            StatusBucketOut(
                gremiumId=r.gremium_id,
                stateId=r.current_state_id,
                count=int(r.application_count),
            )
            for r in rows
        ]

    async def stats(
        self,
        *,
        gremium_id: UUID | None = None,
        period: str | None = None,
        budget_pot_id: UUID | None = None,
    ) -> BudgetStatsOut:
        """Kombinierte Rollup-Antwort (Auslastung + Statusverteilung)."""
        return BudgetStatsOut(
            pots=await self.usage(
                gremium_id=gremium_id, period=period, budget_pot_id=budget_pot_id
            ),
            statusDistribution=await self.status_distribution(gremium_id=gremium_id),
        )


def _as_decimal(value: object) -> Decimal:
    """MV-Summe → ``Decimal`` (NULL/0 robust)."""
    if value is None:
        return Decimal("0")
    return value if isinstance(value, Decimal) else Decimal(str(value))
