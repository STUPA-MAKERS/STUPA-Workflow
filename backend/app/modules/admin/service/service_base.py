"""Shared base of the ``service.ConfigService`` ops classes.

The base holds the session-bound constructor, the audit hook that every
mutation uses, and the ISO datetime helper of the RBAC and webhook concerns. The
optional object storage serves the logo files of a variant and the file objects that
a gremium delete removes.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.modules.audit.service import record as audit_record

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.audit.actions import AuditAction
    from app.modules.files.storage import ObjectStorage


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class ConfigServiceBase:
    """Admin config operations bound to one ``AsyncSession`` — shared base."""

    def __init__(self, session: AsyncSession, *, storage: ObjectStorage | None = None) -> None:
        """Bind the service to a session and the optional object storage."""
        self.session = session
        self.storage = storage

    async def _audit(
        self,
        actor: str,
        action: AuditAction,
        target_type: str,
        target_id: UUID,
        data: dict[str, Any] | None = None,
    ) -> None:
        await audit_record(
            self.session,
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            data=data or {},
        )
