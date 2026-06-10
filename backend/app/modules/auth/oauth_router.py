"""OAuth2-Authorization-Server-Endpunkte für native/MCP-Clients (#MCP).

Flow (Authorization Code + PKCE, RFC 6749/7636):

1. ``GET /api/oauth/authorize`` — validiert client_id/redirect_uri (nur Loopback) +
   PKCE-Challenge, legt den Request signiert im ``ap_oauth_tx``-Cookie ab und schickt den
   Browser in den **bestehenden** Keycloak-Login (``/api/auth/login``).
2. Nach dem OIDC-Callback (Session gesetzt) leitet dieser bei vorhandenem
   ``ap_oauth_tx`` auf ``GET /api/oauth/finish`` — dort wird ein einmaliger
   Authorization-Code für den eingeloggten Principal gemintet und an die Loopback-
   ``redirect_uri`` zurückgegeben.
3. ``POST /api/oauth/token`` — tauscht Code (PKCE-verifiziert) bzw. Refresh-Token gegen
   ein opakes, **scoped** Access-/Refresh-Token-Paar.

Token landen nur hier (Body der Token-Antwort) im Klartext; DB hält ausschließlich
SHA-256-Hashes. Scopes kappen die Permissions zur Laufzeit (``deps.get_current_principal``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from app.deps import DbSession, Principal, SettingsDep, require_principal
from app.modules.auth import oauth, oauth_service, sessions
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.oauth_models import OAuthToken
from app.shared.errors import BadRequestError, ForbiddenError, NotFoundError

router = APIRouter(prefix="/oauth", tags=["oauth"])
well_known_router = APIRouter(tags=["oauth"])

_TX_MAX_AGE = 600  # authorize→finish über den OIDC-Hop: 10-min-Fenster
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _cookie_kwargs(settings: SettingsDep) -> dict[str, object]:
    return {
        "httponly": True,
        "secure": settings.cookie_secure,
        "samesite": "lax",
        "path": "/",
    }


def _is_loopback_redirect(redirect_uri: str) -> bool:
    """Nur http-Loopback-Redirects (native-App-Pattern, RFC 8252) zulassen."""
    try:
        u = urlparse(redirect_uri)
    except ValueError:
        return False
    return u.scheme == "http" and (u.hostname or "") in _LOOPBACK_HOSTS


def _redirect_error(redirect_uri: str, *, error: str, state: str) -> RedirectResponse:
    params = {"error": error}
    if state:
        params["state"] = state
    sep = "&" if urlparse(redirect_uri).query else "?"
    return RedirectResponse(
        f"{redirect_uri}{sep}{urlencode(params)}",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/authorize", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
def authorize(
    settings: SettingsDep,
    response_type: Annotated[str, Query()] = "",
    client_id: Annotated[str, Query()] = "",
    redirect_uri: Annotated[str, Query()] = "",
    code_challenge: Annotated[str, Query()] = "",
    code_challenge_method: Annotated[str, Query()] = "",
    scope: Annotated[str, Query()] = "",
    state: Annotated[str, Query()] = "",
) -> RedirectResponse:
    """Authorize-Request validieren → OIDC-Login starten (Request im tx-Cookie)."""
    if not settings.oidc_enabled:
        raise NotFoundError("OAuth is not configured.")
    # client_id + redirect_uri zuerst: bei ungültigem Redirect NICHT dorthin
    # umleiten (Open-Redirect/Spoofing), sondern 400.
    if client_id != settings.oauth_mcp_client_id:
        raise BadRequestError("Unknown client_id.")
    if not _is_loopback_redirect(redirect_uri):
        raise BadRequestError("redirect_uri must be an http loopback URI.")
    # Ab hier ist die redirect_uri vertrauenswürdig → Protokollfehler dorthin melden.
    if response_type != "code":
        return _redirect_error(redirect_uri, error="unsupported_response_type", state=state)
    if code_challenge_method != "S256" or not code_challenge:
        return _redirect_error(redirect_uri, error="invalid_request", state=state)
    try:
        scopes = oauth.parse_scope(scope)
    except oauth.OAuthError as exc:
        return _redirect_error(redirect_uri, error=exc.error, state=state)

    tx = sessions.issue_oauth_tx(
        settings.session_secret,
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "scope": " ".join(scopes),
            "state": state,
        },
    )
    # Bestehenden OIDC-Login anstoßen; der Callback leitet bei vorhandenem
    # ap_oauth_tx-Cookie auf /api/oauth/finish (siehe auth/router.callback).
    login_url = settings.public_base_url.rstrip("/") + "/api/auth/login"
    resp = RedirectResponse(login_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    resp.set_cookie(
        settings.oauth_tx_cookie_name,
        tx,
        max_age=_TX_MAX_AGE,
        **_cookie_kwargs(settings),  # type: ignore[arg-type]
    )
    return resp


@router.get("/finish", status_code=status.HTTP_302_FOUND)
async def finish(
    request: Request,
    db: DbSession,
    settings: SettingsDep,
    principal: Annotated[Principal, Depends(require_principal())],
) -> RedirectResponse:
    """Nach OIDC-Login: Authorization-Code minten + an die Loopback-redirect_uri geben."""
    tx_cookie = request.cookies.get(settings.oauth_tx_cookie_name)
    tx = (
        sessions.load_oauth_tx(settings.session_secret, tx_cookie, _TX_MAX_AGE)
        if tx_cookie
        else None
    )
    if tx is None:
        raise BadRequestError("Invalid or expired OAuth transaction.")
    # Agent-Zugang muss explizit erlaubt sein (Admin bypasst). Ohne `mcp.use` wird
    # KEIN Code gemintet → kein Token (zentraler Chokepoint, #MCP).
    if not principal.has("mcp.use"):
        raise ForbiddenError("Missing permission: mcp.use")
    # Principal-Row-Id über den sub auflösen (require_principal liefert nur den
    # aufgelösten Principal; die Code-Zeile braucht die principal.id).
    row_id = (
        await db.execute(select(PrincipalRow.id).where(PrincipalRow.sub == principal.sub))
    ).scalar_one_or_none()
    if row_id is None:
        raise BadRequestError("Principal not found.")

    code = await oauth_service.create_authorization_code(
        db,
        principal_id=row_id,
        client_id=tx["client_id"],
        redirect_uri=tx["redirect_uri"],
        code_challenge=tx["code_challenge"],
        scope=tx["scope"],
        now=datetime.now(UTC),
        ttl_seconds=settings.oauth_code_ttl_seconds,
    )
    await db.commit()

    params = {"code": code}
    if tx["state"]:
        params["state"] = tx["state"]
    sep = "&" if urlparse(tx["redirect_uri"]).query else "?"
    resp = RedirectResponse(
        f"{tx['redirect_uri']}{sep}{urlencode(params)}",
        status_code=status.HTTP_302_FOUND,
    )
    resp.delete_cookie(settings.oauth_tx_cookie_name, path="/")
    return resp


def _token_error(error: str, description: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": error, "error_description": description}, status_code=code)


@router.post("/token")
async def token(
    db: DbSession,
    settings: SettingsDep,
    grant_type: Annotated[str, Form()] = "",
    code: Annotated[str, Form()] = "",
    code_verifier: Annotated[str, Form()] = "",
    redirect_uri: Annotated[str, Form()] = "",
    refresh_token: Annotated[str, Form()] = "",
    client_id: Annotated[str, Form()] = "",
) -> JSONResponse:
    """Authorization-Code bzw. Refresh-Token → opakes, scoped Token-Paar (RFC 6749)."""
    if not settings.oidc_enabled:
        return _token_error("invalid_request", "OAuth is not configured.", 404)
    if client_id != settings.oauth_mcp_client_id:
        return _token_error("invalid_client", "unknown client_id.", 401)
    now = datetime.now(UTC)
    try:
        if grant_type == "authorization_code":
            issued = await oauth_service.exchange_code(
                db,
                code=code,
                code_verifier=code_verifier,
                redirect_uri=redirect_uri,
                client_id=client_id,
                now=now,
                access_ttl=settings.oauth_access_ttl_seconds,
                refresh_ttl=settings.oauth_refresh_ttl_seconds,
            )
        elif grant_type == "refresh_token":
            issued = await oauth_service.refresh_tokens(
                db,
                refresh_token=refresh_token,
                client_id=client_id,
                now=now,
                access_ttl=settings.oauth_access_ttl_seconds,
                refresh_ttl=settings.oauth_refresh_ttl_seconds,
            )
        else:
            return _token_error("unsupported_grant_type", f"grant_type={grant_type!r}")
    except oauth.OAuthError as exc:
        return _token_error(exc.error, exc.description)
    await db.commit()
    return JSONResponse(
        {
            "access_token": issued.access_token,
            "token_type": "Bearer",
            "expires_in": issued.expires_in,
            "refresh_token": issued.refresh_token,
            "scope": issued.scope,
        }
    )


async def _principal_row_id(db: DbSession, principal: Principal) -> Any:
    return (
        await db.execute(select(PrincipalRow.id).where(PrincipalRow.sub == principal.sub))
    ).scalar_one_or_none()


@router.get("/grants")
async def list_grants(
    db: DbSession,
    principal: Annotated[Principal, Depends(require_principal())],
) -> list[dict[str, Any]]:
    """Aktive (nicht widerrufene) OAuth-Grants des eingeloggten Nutzers (Self-Service)."""
    pid = await _principal_row_id(db, principal)
    if pid is None:
        return []
    rows = (
        await db.execute(
            select(OAuthToken)
            .where(OAuthToken.principal_id == pid, OAuthToken.revoked_at.is_(None))
            .order_by(OAuthToken.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "clientId": r.client_id,
            "scope": r.scope,
            "createdAt": r.created_at.isoformat() if r.created_at else None,
            "accessExpiresAt": r.access_expires_at.isoformat(),
            "refreshExpiresAt": (
                r.refresh_expires_at.isoformat() if r.refresh_expires_at else None
            ),
        }
        for r in rows
    ]


@router.delete("/grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_grant(
    grant_id: str,
    db: DbSession,
    principal: Annotated[Principal, Depends(require_principal())],
) -> None:
    """Einen eigenen Grant widerrufen (Access+Refresh sofort ungültig). 404 wenn fremd."""
    pid = await _principal_row_id(db, principal)
    row = (
        await db.execute(select(OAuthToken).where(OAuthToken.id == grant_id))
    ).scalar_one_or_none()
    if row is None or pid is None or row.principal_id != pid:
        raise NotFoundError("Grant not found.")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        await db.commit()


@router.delete("/grants", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_grants(
    db: DbSession,
    principal: Annotated[Principal, Depends(require_principal())],
) -> None:
    """Alle eigenen Grants widerrufen (Not-Aus für alle Agenten dieses Nutzers)."""
    pid = await _principal_row_id(db, principal)
    if pid is None:
        return
    rows = (
        await db.execute(
            select(OAuthToken).where(
                OAuthToken.principal_id == pid, OAuthToken.revoked_at.is_(None)
            )
        )
    ).scalars().all()
    now = datetime.now(UTC)
    for r in rows:
        r.revoked_at = now
    await db.commit()


@well_known_router.get("/.well-known/oauth-authorization-server")
def authorization_server_metadata(settings: SettingsDep) -> JSONResponse:
    """RFC 8414 AS-Metadata für die Client-Discovery."""
    base = settings.public_base_url.rstrip("/")
    return JSONResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/api/oauth/authorize",
            "token_endpoint": f"{base}/api/oauth/token",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": sorted(oauth.SCOPES.keys()),
        }
    )


@well_known_router.get("/.well-known/oauth-protected-resource")
def protected_resource_metadata(settings: SettingsDep) -> JSONResponse:
    """RFC 9728 Protected-Resource-Metadata (MCP-Discovery)."""
    base = settings.public_base_url.rstrip("/")
    return JSONResponse(
        {
            "resource": f"{base}/api",
            "authorization_servers": [base],
            "scopes_supported": sorted(oauth.SCOPES.keys()),
        }
    )
