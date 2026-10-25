"""Lifetimes of a principal session (OIDC login).

One row (`login_settings`, id=1) holds two values:

- `web_session_days`: the lifetime of a login in a browser tab (default 90).
- `pwa_session_days`: the lifetime of a login in the installed app (default 180).

A session ends after that many days without use. Each check at the IdP
(`session_renewal`) moves the end, so a change applies to every session at its next
check. `GET/PUT /admin/login-settings` (`admin.users`) reads and writes the row. The
PUT writes a `config_change` audit entry without a revision, so the audit log cannot
revert it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import (
    DEFAULT_PWA_SESSION_DAYS,
    DEFAULT_WEB_SESSION_DAYS,
    SESSION_CLIENT_PWA,
    LoginSettings,
)

AUDIT_TARGET_TYPE = "login_settings"


def _defaults() -> LoginSettings:
    return LoginSettings(
        id=1,
        web_session_days=DEFAULT_WEB_SESSION_DAYS,
        pwa_session_days=DEFAULT_PWA_SESSION_DAYS,
    )


async def load_login_settings(session: AsyncSession) -> LoginSettings:
    """Return the settings row, or a transient row with the defaults.

    The migration inserts the row. A schema built from the metadata alone (tests, a
    fresh baseline) can lack it. The defaults then apply. The function writes nothing.
    """
    row = await session.get(LoginSettings, 1)
    return row if row is not None else _defaults()


def session_days(settings: LoginSettings, client: str) -> int:
    """Return the lifetime in days for a session client (`web` or `pwa`)."""
    if client == SESSION_CLIENT_PWA:
        return settings.pwa_session_days
    return settings.web_session_days


class LoginSettingsService:
    """Read and change the session lifetimes."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the service to a database session."""
        self.session = session

    async def get(self) -> LoginSettings:
        """Return the settings row. Create it with the defaults when it is missing."""
        row = await self.session.get(LoginSettings, 1)
        if row is None:
            row = _defaults()
            row.updated_at = datetime.now(UTC)
            self.session.add(row)
            await self.session.flush()
        return row

    async def update(
        self, *, web_session_days: int, pwa_session_days: int, actor: str
    ) -> LoginSettings:
        """Replace both values and write a `config_change` audit entry.

        The entry holds the old and the new values. It has no `revisionId`, so the
        audit log does not offer a revert. The method commits.
        """
        row = await self.get()
        data: dict[str, Any] = {
            "webSessionDays": {"from": row.web_session_days, "to": web_session_days},
            "pwaSessionDays": {"from": row.pwa_session_days, "to": pwa_session_days},
        }
        row.web_session_days = web_session_days
        row.pwa_session_days = pwa_session_days
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
