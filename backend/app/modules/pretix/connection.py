"""The pretix connection: the read, the save, the test and the client of the worker.

One row holds the address, the organizer, the token and the two switches. A save checks
the host of the address against the deploy setting `PRETIX_HOST_ALLOWLIST`
(§NF/security/network/003100) and writes an audit entry without the token
(§F/integrations/pretix/003080). No read returns the token (§NF/security/network/003101).

No function here commits. The router owns the transaction.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.pretix.client import PretixClient, PretixError, address_allowed, normalize_url
from app.modules.pretix.models import PretixSettings
from app.modules.pretix.schemas import ConnectionIn, ConnectionOut, ConnectionTestOut
from app.settings import Settings
from app.shared.errors import ValidationProblem

#: The parts of the integration that have a switch (§F/integrations/pretix/003082).
Part = Literal["sales", "income"]

#: The problem code of an address change that keeps the stored token.
TOKEN_REQUIRED = "token_required"

ClientFactory = Callable[[str, str, str, tuple[str, ...]], PretixClient]


def default_client(
    base_url: str, organizer: str, token: str, allowlist: tuple[str, ...]
) -> PretixClient:
    """Build the client of a connection."""
    return PretixClient(base_url=base_url, organizer=organizer, token=token, allowlist=allowlist)


def connected(row: PretixSettings) -> bool:
    """Tell whether the connection has an address, an organizer and a token."""
    return bool(row.base_url and row.organizer and row.token)


def part_on(row: PretixSettings, part: Part) -> bool:
    """Tell whether a part is on: its switch is on and the connection is complete (003082)."""
    match part:
        case "sales":
            return connected(row) and bool(row.show_sales)
        case "income":
            return connected(row) and bool(row.book_income)


@dataclass(frozen=True, slots=True)
class ConnectionService:
    """The pretix connection, bound to one session."""

    session: AsyncSession
    settings: Settings
    client_factory: ClientFactory = default_client

    async def row(self) -> PretixSettings:
        """Return the single row, and create it when it does not exist."""
        await self.session.execute(pg_insert(PretixSettings).values(id=1).on_conflict_do_nothing())
        found = await self.session.scalar(
            select(PretixSettings)
            .where(PretixSettings.id == 1)
            .execution_options(populate_existing=True)
        )
        if found is None:  # pragma: no cover - the insert above made the row
            raise RuntimeError("pretix_settings has no row")
        return found

    def _out(self, row: PretixSettings) -> ConnectionOut:
        return ConnectionOut(
            base_url=row.base_url,
            organizer=row.organizer,
            token_set=bool(row.token),
            show_sales=bool(row.show_sales),
            book_income=bool(row.book_income),
            allowed_hosts=tuple(self.settings.pretix_host_allowlist),
        )

    async def read(self) -> ConnectionOut:
        """Return the connection without its token."""
        return self._out(await self.row())

    async def save(self, data: ConnectionIn, *, actor: str) -> ConnectionOut:
        """Save the connection and the switches, and write the audit entry.

        Raises:
            ValidationProblem: The host of the address is not in the allowlist (422
                `pretix_host_not_allowed`), or the address changes without a new token
                while a token is stored (422 `token_required`).
        """
        base_url = (normalize_url(data.base_url) if data.base_url else "") or None
        if base_url is not None and not address_allowed(
            base_url, self.settings.pretix_host_allowlist
        ):
            raise ValidationProblem(
                "The host of this address is not in PRETIX_HOST_ALLOWLIST.",
                code="pretix_host_not_allowed",
                errors=[{"field": "baseUrl", "msg": "host not allowed"}],
            )
        organizer = (data.organizer or "").strip() or None
        before = await self.row()
        old_token = before.token
        moved = base_url != before.base_url or organizer != before.organizer
        if (
            base_url is not None
            and moved
            and old_token
            and data.token is None
            and not data.clear_token
        ):
            raise ValidationProblem(
                "A change of the address needs the token again.",
                code=TOKEN_REQUIRED,
                errors=[{"field": "token", "msg": "token required"}],
            )
        token = None if data.clear_token else (data.token or old_token)
        await self.session.execute(
            update(PretixSettings)
            .where(PretixSettings.id == 1)
            .values(
                base_url=base_url,
                organizer=organizer,
                token=token,
                show_sales=data.show_sales,
                book_income=data.book_income,
            )
        )
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.PRETIX_CONNECTION,
            target_type="pretix_settings",
            target_id="1",
            data={
                "baseUrl": base_url,
                "organizer": organizer,
                "tokenChanged": token != old_token,
                "showSales": data.show_sales,
                "bookIncome": data.book_income,
            },
        )
        return self._out(await self.row())

    async def client(self) -> PretixClient | None:
        """Return the client of the stored connection, or None while it is incomplete."""
        row = await self.row()
        if not row.base_url or not row.organizer or not row.token:
            return None
        return self.client_factory(
            row.base_url, row.organizer, row.token, tuple(self.settings.pretix_host_allowlist)
        )

    async def test(self) -> ConnectionTestOut:
        """Call pretix with the stored connection and tell the result."""
        client = await self.client()
        if client is None:
            return ConnectionTestOut(ok=False, error="not_configured")
        try:
            await client.check()
        except PretixError as exc:
            return ConnectionTestOut(ok=False, error=exc.code)
        return ConnectionTestOut(ok=True, name=client.organizer)
