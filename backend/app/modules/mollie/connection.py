"""The Mollie connection: the read, the save, the test and the client of the worker.

One row holds the token and the two cost centres of the bookings. A save writes an audit
entry without the token (§F/integrations/mollie/003092). No read returns the token
(§NF/security/network/003101).

No function here commits. The router owns the transaction.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.mollie.client import MollieClient, MollieError
from app.modules.mollie.models import MollieSettings
from app.modules.mollie.schemas import ConnectionIn, ConnectionOut, ConnectionTestOut

ClientFactory = Callable[[str], MollieClient]


def default_client(token: str) -> MollieClient:
    """Build the client of a connection."""
    return MollieClient(token=token)


def connected(row: MollieSettings) -> bool:
    """Tell whether the connection has a token."""
    return bool(row.token)


@dataclass(frozen=True, slots=True)
class ConnectionService:
    """The Mollie connection, bound to one session."""

    session: AsyncSession
    client_factory: ClientFactory = default_client

    async def row(self) -> MollieSettings:
        """Return the single row, and create it when it does not exist."""
        await self.session.execute(pg_insert(MollieSettings).values(id=1).on_conflict_do_nothing())
        found = await self.session.scalar(
            select(MollieSettings)
            .where(MollieSettings.id == 1)
            .execution_options(populate_existing=True)
        )
        if found is None:  # pragma: no cover - the insert above made the row
            raise RuntimeError("mollie_settings has no row")
        return found

    @staticmethod
    def _out(row: MollieSettings) -> ConnectionOut:
        return ConnectionOut(
            token_set=bool(row.token),
            organization=row.organization,
            fee_budget_id=row.fee_budget_id,
            unassigned_budget_id=row.unassigned_budget_id,
            read_ok_at=row.read_ok_at,
            read_error=row.read_error,
        )

    async def read(self) -> ConnectionOut:
        """Return the connection without its token."""
        return self._out(await self.row())

    async def save(self, data: ConnectionIn, *, actor: str) -> ConnectionOut:
        """Save the token and the cost centres, and write the audit entry."""
        before = await self.row()
        token = None if data.clear_token else (data.token or before.token)
        await self.session.execute(
            update(MollieSettings)
            .where(MollieSettings.id == 1)
            .values(
                token=token,
                organization=before.organization if token == before.token else None,
                fee_budget_id=data.fee_budget_id,
                unassigned_budget_id=data.unassigned_budget_id,
            )
        )
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.MOLLIE_CONNECTION,
            target_type="mollie_settings",
            target_id="1",
            data={
                "tokenChanged": token != before.token,
                "feeBudgetId": str(data.fee_budget_id) if data.fee_budget_id else None,
                "unassignedBudgetId": (
                    str(data.unassigned_budget_id) if data.unassigned_budget_id else None
                ),
            },
        )
        return self._out(await self.row())

    async def client(self) -> MollieClient | None:
        """Return the client of the stored connection, or None without a token."""
        row = await self.row()
        return self.client_factory(row.token) if row.token else None

    async def test(self) -> ConnectionTestOut:
        """Call Mollie with the stored token, keep the name of the organization, tell it."""
        client = await self.client()
        if client is None:
            return ConnectionTestOut(ok=False, error="not_configured")
        try:
            name = await client.organization()
        except MollieError as exc:
            return ConnectionTestOut(ok=False, error=exc.code)
        await self.session.execute(
            update(MollieSettings).where(MollieSettings.id == 1).values(organization=name)
        )
        return ConnectionTestOut(ok=True, name=name)
