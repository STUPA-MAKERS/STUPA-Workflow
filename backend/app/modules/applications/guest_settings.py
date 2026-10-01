"""Settings for applications without an account (Z1).

One row (`guest_application_settings`, id=1) holds two values:

- `confirm_ttl_hours`: the time a guest has to confirm the email. The deadline worker
  discards an unconfirmed application after it.
- `link_ttl_days`: the lifetime of a new magic link. NULL means no expiry.

`GET/PUT /admin/guest-settings` (`admin.deadlines`) reads and writes the row. The PUT
writes a `config_change` audit entry without a revision, so the audit log cannot revert
it. The public `GET /site-config` returns `confirmTtlHours` for the confirmation page.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import (
    DEFAULT_CONFIRM_TTL_HOURS,
    GuestApplicationSettings,
)
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record

AUDIT_TARGET_TYPE = "guest_application_settings"


async def load_guest_settings(session: AsyncSession) -> GuestApplicationSettings:
    """Return the settings row, or a transient row with the defaults.

    The migration inserts the row. A schema built from the metadata alone (tests,
    a fresh baseline) can lack it. The defaults then apply: 12 hours to confirm and
    links without an expiry. The function writes nothing.
    """
    row = await session.get(GuestApplicationSettings, 1)
    if row is not None:
        return row
    return GuestApplicationSettings(
        id=1, confirm_ttl_hours=DEFAULT_CONFIRM_TTL_HOURS, link_ttl_days=None
    )


class GuestSettingsService:
    """Read and change the guest application settings."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self) -> GuestApplicationSettings:
        """Return the settings row. Create it with the defaults when it is missing."""
        row = await self.session.get(GuestApplicationSettings, 1)
        if row is None:
            row = GuestApplicationSettings(
                id=1,
                confirm_ttl_hours=DEFAULT_CONFIRM_TTL_HOURS,
                link_ttl_days=None,
                updated_at=datetime.now(UTC),
            )
            self.session.add(row)
            await self.session.flush()
        return row

    async def update(
        self, *, confirm_ttl_hours: int, link_ttl_days: int | None, actor: str
    ) -> GuestApplicationSettings:
        """Replace both values and write a `config_change` audit entry.

        The entry holds the old and the new values. It has no `revisionId`, so the
        audit log does not offer a revert. The method commits.
        """
        row = await self.get()
        data: dict[str, Any] = {
            "confirmTtlHours": {"from": row.confirm_ttl_hours, "to": confirm_ttl_hours},
            "linkTtlDays": {"from": row.link_ttl_days, "to": link_ttl_days},
        }
        row.confirm_ttl_hours = confirm_ttl_hours
        row.link_ttl_days = link_ttl_days
        row.updated_at = datetime.now(UTC)
        row.updated_by = actor
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.CONFIG_CHANGE,
            target_type=AUDIT_TARGET_TYPE,
            target_id="1",
            data=data,
        )
        await self.session.commit()
        await self.session.refresh(row)
        return row
