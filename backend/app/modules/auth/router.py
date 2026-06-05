"""Auth-Endpunkte (api.md §3 »auth«).

OIDC-Login/Callback (Keycloak, Auth Code + PKCE), Server-Session-Cookie,
Magic-Link issue/verify, `/auth/me`, Logout. Token landen nie im JS — nur
HttpOnly+Secure+SameSite=Lax-Cookies bzw. der signierte Applicant-Token im Body.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.deps import DbSession, Principal, SettingsDep, require_principal
from app.modules.auth import oidc, service, sessions
from app.modules.auth.oidc import OidcError
from app.modules.auth.schemas import (
    MagicLinkRequest,
    MagicLinkVerifyOut,
    MagicLinkVerifyRequest,
    MeOut,
)
from app.shared.errors import BadRequestError, NotFoundError, ProblemDetail

router = APIRouter(prefix="/auth", tags=["auth"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}
_TX_MAX_AGE = 600  # OIDC-Transaktion: 10 min Fenster für Authorize→Callback.


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Problem-JSON für die angegebenen Fehler-Statuscodes dokumentieren."""
    return {code: _PROBLEM for code in codes}


def _cookie_kwargs(settings: SettingsDep) -> dict[str, object]:
    return {
        "httponly": True,
        "secure": settings.cookie_secure,
        "samesite": "lax",
        "path": "/",
    }


@router.get(
    "/login",
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    responses=_errors(404),
)
def login(settings: SettingsDep) -> RedirectResponse:
    """Redirect zu Keycloak (Auth Code + PKCE). state/verifier/nonce im tx-Cookie."""
    if not settings.oidc_enabled:
        raise NotFoundError("OIDC is not configured.")
    verifier, challenge = oidc.generate_pkce()
    state = oidc.generate_state()
    nonce = oidc.generate_nonce()
    url = oidc.authorization_url(settings, state=state, challenge=challenge, nonce=nonce)
    response = RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    response.set_cookie(
        settings.oidc_tx_cookie_name,
        sessions.issue_oidc_tx(settings.session_secret, state, verifier, nonce),
        max_age=_TX_MAX_AGE,
        **_cookie_kwargs(settings),  # type: ignore[arg-type]
    )
    return response


@router.get(
    "/callback",
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    responses=_errors(400, 404),
)
async def callback(
    request: Request,
    db: DbSession,
    settings: SettingsDep,
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
) -> RedirectResponse:
    """Code→Token→Session. CSRF/Replay-Schutz via state-Abgleich + nonce im id_token."""
    if not settings.oidc_enabled:
        raise NotFoundError("OIDC is not configured.")
    tx_cookie = request.cookies.get(settings.oidc_tx_cookie_name)
    tx = (
        sessions.load_oidc_tx(settings.session_secret, tx_cookie, _TX_MAX_AGE)
        if tx_cookie
        else None
    )
    if tx is None or tx["state"] != state:
        raise BadRequestError("Invalid or expired OIDC transaction.")
    try:
        cookie, _ = await service.oidc_callback(
            db, settings, code=code, verifier=tx["verifier"], nonce=tx["nonce"]
        )
    except OidcError as exc:
        raise BadRequestError("OIDC login failed.") from exc

    response = RedirectResponse(
        settings.public_base_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT
    )
    response.set_cookie(
        settings.session_cookie_name,
        cookie,
        max_age=settings.session_ttl_hours * 3600,
        **_cookie_kwargs(settings),  # type: ignore[arg-type]
    )
    response.delete_cookie(settings.oidc_tx_cookie_name, path="/")
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, db: DbSession, settings: SettingsDep) -> Response:
    """Server-Session beenden + Cookie löschen (idempotent)."""
    cookie = request.cookies.get(settings.session_cookie_name)
    if cookie:
        await sessions.delete_principal_session(
            db,
            secret=settings.session_secret,
            cookie_value=cookie,
            max_age=settings.session_ttl_hours * 3600,
        )
        await db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return response


@router.get("/me", responses=_errors(401, 403))
def me(principal: Annotated[Principal, Depends(require_principal())]) -> MeOut:
    """Principal + aufgelöste Rollen/Permissions/Gruppen."""
    return MeOut(
        sub=principal.sub,
        email=principal.email,
        display_name=principal.display_name,
        roles=sorted(principal.roles),
        permissions=sorted(principal.permissions),
        groups=sorted(principal.groups),
    )


@router.post(
    "/magic-link",
    status_code=status.HTTP_202_ACCEPTED,
    responses=_errors(400),
)
async def request_magic_link(
    body: MagicLinkRequest, db: DbSession, settings: SettingsDep
) -> dict[str, str]:
    """Magic-Link anfordern. Anti-Enumeration: **immer** 202 + konstanter Body,
    kein Treffer-Leak (ob Mail/Antrag existiert)."""
    await service.request_magic_link(
        db, settings, email=str(body.email), application_id=body.application_id
    )
    await db.commit()
    return {"status": "accepted"}


@router.post(
    "/magic-link/verify",
    responses=_errors(400, 410),
)
async def verify_magic_link(
    body: MagicLinkVerifyRequest,
    db: DbSession,
    settings: SettingsDep,
    response: Response,
) -> MagicLinkVerifyOut:
    """Token→Applicant-Session (Scope = genau eine App). Abgelaufen/verbraucht → 410."""
    app_id, scope, token = await service.verify_magic_link(
        db, settings, token=body.token
    )
    await db.commit()
    response.set_cookie(
        settings.applicant_cookie_name,
        token,
        max_age=settings.session_ttl_hours * 3600,
        **_cookie_kwargs(settings),  # type: ignore[arg-type]
    )
    return MagicLinkVerifyOut(application_id=app_id, scope=scope, token=token)  # type: ignore[arg-type]
