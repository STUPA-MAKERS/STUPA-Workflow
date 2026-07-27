"""Shared base of the ``service.ConfigService`` ops classes.

The base holds the session-bound constructor, the audit hook that every
mutation uses, and the datetime helpers of the RBAC and webhook concerns.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.modules.audit.service import record as audit_record
from app.shared.errors import ValidationProblem

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.audit.actions import AuditAction


def _parse_dt(value: str | None) -> datetime | None:
    """Parse an ISO-8601 string into a tz-aware UTC ``datetime``.

    ``role_assignment.valid_from`` and ``valid_until`` are ``timestamptz``. The
    service stores aware UTC values, so validity windows compare correctly in
    the RBAC resolver. A naive input counts as UTC. An aware input moves to UTC.

    Raises:
        ValidationProblem: The value is not a valid ISO-8601 datetime.
    """
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValidationProblem(
            "Invalid datetime.", errors=[{"field": "validFrom/validUntil", "msg": str(exc)}]
        ) from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class ConfigServiceBase:
    """Admin config operations bound to one ``AsyncSession`` — shared base."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _audit(
        self,
        actor: str,
        action: AuditAction,
        target_type: str,
        target_id: UUID,
        data: dict | None = None,
    ) -> None:
        await audit_record(
            self.session,
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            data=data or {},
        )
