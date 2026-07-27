"""FastAPI auth dependencies.

`get_current_principal` resolves a session cookie or an OAuth bearer token to an
RBAC-resolved principal. `get_current_applicant` resolves a signed opaque `sid`
from a bearer header or a cookie to an applicant session and its scope.
`require_principal`, `require_group` and `require_applicant` raise 401 without
authentication and 403 when the permission, the group or the scope is missing.

`Principal` and `Applicant` come from `app.modules.auth.principal`. That module is
a leaf, so the re-export avoids an import cycle between `deps` and `auth`.
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
    """Read the applicant token from `Authorization: Bearer` or the HttpOnly cookie.

    The function does not accept a `?t=` query parameter on purpose. A token in the
    query string leaks through the Referer header, the browser history and the logs.
    The magic link carries its token in the URL fragment. The frontend exchanges the
    fragment for the cookie with a POST request.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get(settings.applicant_cookie_name)


def _principal_bearer_token(request: Request) -> str | None:
    """Return the OAuth access token from `Authorization: Bearer apat_…`, else `None`.

    Only the `apat_` prefix counts as a principal token. This function ignores a
    signed applicant bearer token from a magic link. The applicant path handles it.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    return token if oauth.is_access_token(token) else None


async def _principal_from_access_token(
    db: AsyncSession, token: str, now: datetime
) -> Principal | None:
    """Resolve an OAuth access token to a scoped principal.

    Returns:
        The scoped principal, or `None` when the token is invalid or expired.
    """
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
    # Kill switch: revoking `mcp.use` must invalidate already-issued tokens, so
    # re-check against the UNSCOPED permission set (before scope capping).
    if not principal.has("mcp.use"):
        return None
    principal.scope_permissions = oauth.scope_permissions(oauth.parse_scope(scope))
    return principal


async def get_current_principal(
    request: Request,
    db: DbSession,
    settings: SettingsDep,
) -> Principal | None:
    """Resolve the principal from an OAuth bearer token (MCP) or the session cookie.

    The function tries a `Bearer apat_…` token first and caps the permissions to
    the token scope. Without such a token it falls back to the session cookie.

    Returns:
        The resolved principal, or `None` when no credential is valid.
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
    db: DbSession,
    settings: SettingsDep,
) -> Applicant | None:
    """Resolve the server-side magic-link session (signed opaque `sid`) to an Applicant.

    The function checks the signature of the `sid` first. It then looks the `sid` up
    in `applicant_session`. Access needs a row that exists, is not revoked and is not
    expired. A token forged from `SESSION_SECRET` alone matches no row and gives
    `None`.
    """
    token = _bearer_token(request, settings)
    if not token:
        return None
    row = await sessions.load_applicant_session(
        db,
        secret=settings.session_secret,
        cookie_value=token,
        now=datetime.now(UTC),
        max_age=settings.applicant_session_ttl_hours * 3600,
    )
    if row is None or row.scope not in ("edit", "view"):
        return None
    scope: ApplicantScope = "edit" if row.scope == "edit" else "view"
    return Applicant(application_id=str(row.application_id), scope=scope)


def require_principal(*perms: str) -> Callable[..., Principal]:
    """Return a dependency: 401 without a session, 403 on missing permission."""

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
    """Return a dependency: 401 without a session, 403 unless ANY permission matches.

    Use this for a shared read endpoint that serves several admin areas. One example
    is `/admin/config-schemas`, which the type editor and the branding editor both
    read.
    """

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
    """Return a dependency: 401 without a session, 403 if not in the (gremium) group."""

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
    """Return a dependency: 401 without a valid magic-link token, 403 on insufficient scope."""

    def dependency(
        applicant: Annotated[Applicant | None, Depends(get_current_applicant)],
    ) -> Applicant:
        if applicant is None:
            raise UnauthorizedError("Valid magic-link required.")
        if not applicant.allows(scope):
            raise ForbiddenError(f"Magic-link scope '{applicant.scope}' insufficient.")
        return applicant

    return dependency
