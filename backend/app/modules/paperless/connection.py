"""The Paperless connection: the read, the save, the test and the client of the worker.

One row holds the address, the token and the five switches. A save checks the host of
the address against the deploy setting `PAPERLESS_HOST_ALLOWLIST`
(§NF/security/network/002514) and writes an audit entry without the token
(§F/integrations/paperless/002531). No read returns the token
(§NF/security/network/002515).

No function here commits. The router owns the transaction.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from fastapi import Depends
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import DbSession, SettingsDep
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.paperless.client import (
    PaperlessClient,
    PaperlessError,
    host_allowed,
    normalize_url,
)
from app.modules.paperless.models import PaperlessSettings
from app.modules.paperless.schemas import ConnectionIn, ConnectionOut, ConnectionTestOut
from app.settings import Settings
from app.shared.errors import ValidationProblem

#: The parts of the integration that file documents.
Part = Literal["protocols", "applications", "plans"]

#: The time limit of the connection test, so the admin page gets its answer soon.
TEST_TIMEOUT_SECONDS = 5.0

ClientFactory = Callable[[str, str, tuple[str, ...]], PaperlessClient]


def default_client(base_url: str, token: str, allowlist: tuple[str, ...]) -> PaperlessClient:
    """Build the client of a connection."""
    return PaperlessClient(base_url=base_url, token=token, allowlist=allowlist)


def _since(on: bool, before: datetime | None, now: datetime) -> datetime | None:
    """The moment a switch went on: kept while it stays on, new when it goes on."""
    if not on:
        return None
    return before if before is not None else now


@dataclass(frozen=True, slots=True)
class ConnectionService:
    """The Paperless connection, bound to one session."""

    session: AsyncSession
    settings: Settings
    client_factory: ClientFactory = default_client

    async def row(self) -> PaperlessSettings:
        """Return the single row, and create it when it does not exist."""
        await self.session.execute(
            pg_insert(PaperlessSettings).values(id=1).on_conflict_do_nothing()
        )
        found = await self.session.scalar(
            select(PaperlessSettings)
            .where(PaperlessSettings.id == 1)
            .execution_options(populate_existing=True)
        )
        if found is None:  # pragma: no cover - the insert above made the row
            raise RuntimeError("paperless_settings has no row")
        return found

    def _out(self, row: PaperlessSettings) -> ConnectionOut:
        return ConnectionOut(
            base_url=row.base_url,
            token_set=bool(row.token),
            file_protocols=bool(row.file_protocols),
            file_applications=bool(row.file_applications),
            file_plans=bool(row.file_plans),
            insert_enabled=bool(row.insert_enabled),
            link_enabled=bool(row.link_enabled),
            allowed_hosts=tuple(self.settings.paperless_host_allowlist),
        )

    async def read(self) -> ConnectionOut:
        """Return the connection without its token."""
        return self._out(await self.row())

    async def save(self, data: ConnectionIn, *, actor: str, now: datetime) -> ConnectionOut:
        """Save the connection and the switches, and write the audit entry.

        Raises:
            ValidationProblem: The host of the address is not in the allowlist (422
                `paperless_host_not_allowed`).
        """
        base_url = (normalize_url(data.base_url) if data.base_url else "") or None
        if base_url is not None and not host_allowed(
            base_url, self.settings.paperless_host_allowlist
        ):
            raise ValidationProblem(
                "The host of this address is not in PAPERLESS_HOST_ALLOWLIST.",
                code="paperless_host_not_allowed",
                errors=[{"field": "baseUrl", "msg": "host not allowed"}],
            )
        before = await self.row()
        old_token = before.token
        token = None if data.clear_token else (data.token or old_token)
        await self.session.execute(
            update(PaperlessSettings)
            .where(PaperlessSettings.id == 1)
            .values(
                base_url=base_url,
                token=token,
                file_protocols=data.file_protocols,
                protocols_since=_since(data.file_protocols, before.protocols_since, now),
                file_applications=data.file_applications,
                applications_since=_since(data.file_applications, before.applications_since, now),
                file_plans=data.file_plans,
                plans_since=_since(data.file_plans, before.plans_since, now),
                insert_enabled=data.insert_enabled,
                link_enabled=data.link_enabled,
            )
        )
        token_changed = token != old_token
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.PAPERLESS_CONNECTION,
            target_type="paperless_settings",
            target_id="1",
            data={
                "baseUrl": base_url,
                "tokenChanged": token_changed,
                "fileProtocols": data.file_protocols,
                "fileApplications": data.file_applications,
                "filePlans": data.file_plans,
                "insertEnabled": data.insert_enabled,
                "linkEnabled": data.link_enabled,
            },
        )
        return self._out(await self.row())

    async def client(self) -> PaperlessClient | None:
        """Return the client of the stored connection, or None without address or token."""
        row = await self.row()
        if not row.base_url or not row.token:
            return None
        return self.client_factory(
            row.base_url, row.token, tuple(self.settings.paperless_host_allowlist)
        )

    async def test(self) -> ConnectionTestOut:
        """Call Paperless with the stored connection and tell the result."""
        client = await self.client()
        if client is None:
            return ConnectionTestOut(ok=False, error="not_configured")
        try:
            await client.check(TEST_TIMEOUT_SECONDS)
        except PaperlessError as exc:
            return ConnectionTestOut(ok=False, error=exc.code)
        return ConnectionTestOut(ok=True)


def part_since(row: PaperlessSettings, part: Part) -> datetime | None:
    """The moment the switch of a part went on, or None while the part is off.

    A part is off while its switch is off or the connection has no address
    (§F/integrations/paperless/002512).
    """
    if not row.base_url or not row.token:
        return None
    match part:
        case "protocols":
            return row.protocols_since if row.file_protocols else None
        case "applications":
            return row.applications_since if row.file_applications else None
        case "plans":
            return row.plans_since if row.file_plans else None


def insert_on(row: PaperlessSettings) -> bool:
    """Tell whether the part `Aus Paperless einfügen` is on.

    The part is off while its switch is off or the connection has no address
    (§F/integrations/paperless/002512).
    """
    return bool(row.base_url and row.token and row.insert_enabled)


def links_on(row: PaperlessSettings) -> bool:
    """Tell whether the part `Paperless-Dokumente verknüpfen` is on.

    The part is off while its switch is off or the connection has no address
    (§F/integrations/paperless/002512, 002767).
    """
    return bool(row.base_url and row.token and row.link_enabled)


def get_connection_service(db: DbSession, settings: SettingsDep) -> ConnectionService:
    """Build the connection service of the request."""
    return ConnectionService(db, settings)


Connection = Annotated[ConnectionService, Depends(get_connection_service)]
