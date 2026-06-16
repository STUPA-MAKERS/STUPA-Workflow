"""Auth-Dependencies (api.md §1, security.md §1/§2) — reale Auflösung (T-10).

- `get_current_principal`: Session-Cookie → `auth_session` → RBAC-aufgelöster Principal.
- `get_current_applicant`: signierter Magic-Link-Token (Bearer / `?t=` / Cookie) → Scope.
- `require_principal(*perms)` 401/403, `require_group(group)` 401/403,
  `require_applicant(scope)` 401 + Scope-Prüfung.

`Principal`/`Applicant` werden aus `app.modules.auth.principal` re-exportiert (leaf →
kein Import-Zyklus deps ↔ auth).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.modules.auth import oauth, oauth_service, rbac, sessions
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Applicant, ApplicantScope, Principal
from app.settings import Settings, get_settings
from app.shared.errors import ForbiddenError, UnauthorizedError

__all__ = [
    "Applicant",
    "ApplicantScope",
    "DbSession",
    "Principal",
    "get_current_applicant",
    "get_current_principal",
    "require_applicant",
    "require_group",
    "require_principal",
]

DbSession = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _bearer_token(request: Request, settings: Settings) -> str | None:
    """Applicant-Token aus `Authorization: Bearer` oder HttpOnly-Cookie.

    **Kein `?t=`-Query** mehr: Token im Query leckt über Referer/History/Logs
    (security.md §1). Der Magic-Link transportiert seinen Token im URL-Fragment; das
    FE tauscht ihn per POST gegen das Cookie."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get(settings.applicant_cookie_name)


def _principal_bearer_token(request: Request) -> str | None:
    """`Authorization: Bearer apat_…` → OAuth-Access-Token (sonst `None`).

    Nur das `apat_`-Präfix gilt als Principal-Token; signierte Applicant-Bearer
    (Magic-Link) werden hier ignoriert und vom Applicant-Pfad behandelt.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    return token if oauth.is_access_token(token) else None


async def _principal_from_access_token(
    db: AsyncSession, token: str, now: datetime
) -> Principal | None:
    """OAuth-Access-Token → scoped Principal (oder `None`, wenn ungültig/abgelaufen)."""
    resolved = await oauth_service.resolve_access_token(db, token=token, now=now)
    if resolved is None:
        return None
    principal_id, scope = resolved
    row = (
        await db.execute(select(PrincipalRow).where(PrincipalRow.id == principal_id))
    ).scalar_one_or_none()
    if row is None or row.active is False:
        return None
    principal = await rbac.resolve_principal(db, row, now)
    # Kill-Switch: Access-Tokens stammen ausschließlich aus dem OAuth-Grant-Flow, der
    # am Consent auf `mcp.use` gegated ist. Wird diese Permission später entzogen,
    # müssen bereits ausgestellte Tokens sofort wirkungslos werden — daher hier gegen
    # die UNGESCOPTE Permission-Menge (vor der Scope-Kappung) erneut prüfen.
    if not principal.has("mcp.use"):
        return None
    principal.scope_permissions = oauth.scope_permissions(oauth.parse_scope(scope))
    return principal


async def get_current_principal(
    request: Request,
    db: DbSession,
    settings: SettingsDep,
) -> Principal | None:
    """Auth → Principal: OAuth-Bearer-Token (MCP) ODER Session-Cookie (Browser).

    Reihenfolge: ein `Authorization: Bearer apat_…`-Token (OAuth-Access-Token) wird
    zuerst aufgelöst und kappt die Permissions auf den Token-Scope; sonst fällt es auf
    das Session-Cookie zurück. `None`, wenn nichts Gültiges vorliegt.
    """
    now = datetime.now(UTC)
    bearer = _principal_bearer_token(request)
    if bearer is not None:
        return await _principal_from_access_token(db, bearer, now)
    cookie = request.cookies.get(settings.session_cookie_name)
    if not cookie:
        return None
    session = await sessions.load_principal_session(
        db,
        secret=settings.session_secret,
        cookie_value=cookie,
        now=now,
        max_age=settings.session_ttl_hours * 3600,
    )
    if session is None:
        return None
    row = (
        await db.execute(
            select(PrincipalRow).where(PrincipalRow.id == session.principal_id)
        )
    ).scalar_one_or_none()
    if row is None or row.active is False:
        return None
    return await rbac.resolve_principal(db, row, now)


async def get_current_applicant(
    request: Request,
    settings: SettingsDep,
) -> Applicant | None:
    """Signierter Magic-Link-Token → Applicant-Scope (oder `None`)."""
    token = _bearer_token(request, settings)
    if not token:
        return None
    data = sessions.load_applicant_token(
        settings.session_secret, token, max_age=settings.session_ttl_hours * 3600
    )
    if data is None or data["scope"] not in ("edit", "view"):
        return None
    scope: ApplicantScope = "edit" if data["scope"] == "edit" else "view"
    return Applicant(application_id=data["aid"], scope=scope)


def require_principal(*perms: str) -> Callable[..., Principal]:
    """401 ohne Session, 403 bei fehlender Permission."""

    def dependency(
        principal: Annotated[Principal | None, Depends(get_current_principal)],
    ) -> Principal:
        if principal is None:
            raise UnauthorizedError("Authentication required.")
        missing = [p for p in perms if not principal.has(p)]
        if missing:
            raise ForbiddenError(f"Missing permission(s): {', '.join(missing)}")
        return principal

    return dependency


def require_any_permission(*perms: str) -> Callable[..., Principal]:
    """401 ohne Session, 403 wenn KEINE der Permissions vorliegt (ANY-of, #6).

    Für geteilte Lese-Endpunkte, die mehrere Admin-Bereiche bedienen
    (z. B. ``/admin/config-schemas`` für Typ- UND Branding-Editoren)."""

    def dependency(
        principal: Annotated[Principal | None, Depends(get_current_principal)],
    ) -> Principal:
        if principal is None:
            raise UnauthorizedError("Authentication required.")
        if not any(principal.has(p) for p in perms):
            raise ForbiddenError(f"Missing permission(s): one of {', '.join(perms)}")
        return principal

    return dependency


def require_group(group: str) -> Callable[..., Principal]:
    """401 ohne Session, 403 wenn Principal nicht in der (Gremium-)Gruppe ist."""

    def dependency(
        principal: Annotated[Principal | None, Depends(get_current_principal)],
    ) -> Principal:
        if principal is None:
            raise UnauthorizedError("Authentication required.")
        if not principal.in_group(group):
            raise ForbiddenError(f"Not a member of group: {group}")
        return principal

    return dependency


def require_applicant(scope: ApplicantScope = "view") -> Callable[..., Applicant]:
    """401 ohne gültigen Magic-Link-Token; 403 wenn der Scope nicht ausreicht."""

    def dependency(
        applicant: Annotated[Applicant | None, Depends(get_current_applicant)],
    ) -> Applicant:
        if applicant is None:
            raise UnauthorizedError("Valid magic-link required.")
        if not applicant.allows(scope):
            raise ForbiddenError(f"Magic-link scope '{applicant.scope}' insufficient.")
        return applicant

    return dependency
