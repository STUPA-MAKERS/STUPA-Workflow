"""Auth-Endpunkte (api.md §3 »auth«).

OIDC-Login/Callback (Keycloak, Auth Code + PKCE), Server-Session-Cookie,
Magic-Link issue/verify, `/auth/me`, Logout. Token landen **nie** im JS oder Body —
ausschließlich HttpOnly+Secure+SameSite=Lax-Cookies.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.db import get_sessionmaker
from app.deps import DbSession, Principal, SettingsDep, require_principal
from app.modules.auth import oidc, service, sessions
from app.modules.auth.oidc import OidcError
from app.modules.auth.schemas import (
    LogoutOut,
    MagicLinkRequest,
    MagicLinkVerifyOut,
    MagicLinkVerifyRequest,
    MeOut,
)
from app.settings import Settings
from app.shared.antiabuse import (
    enforce_auth_payload_limit,
    rate_limit_magic_link,
    rate_limit_magic_link_verify,
    verify_altcha,
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
    # Principal + auth_session persistieren (get_session committet nie selbst); ohne
    # Commit rollt der Request-Close beide Zeilen zurück → /auth/me 401 (konsistent
    # mit verify_magic_link/logout).
    await db.commit()

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


@router.post("/logout")
async def logout(
    request: Request, db: DbSession, settings: SettingsDep, response: Response
) -> LogoutOut:
    """Server-Session beenden + Cookie löschen (idempotent). Liefert für OIDC die
    RP-Initiated-Logout-URL (Keycloak `end_session`, id_token_hint), damit das FE auch
    die IdP-SSO-Session beendet (security.md §2) — sonst überlebt der SSO-Login."""
    logout_url: str | None = None
    cookie = request.cookies.get(settings.session_cookie_name)
    if cookie:
        ended = await sessions.delete_principal_session(
            db,
            secret=settings.session_secret,
            cookie_value=cookie,
            max_age=settings.session_ttl_hours * 3600,
        )
        await db.commit()
        if settings.oidc_enabled and ended is not None:
            logout_url = oidc.end_session_url(settings, id_token=ended.id_token)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return LogoutOut(logout_url=logout_url)


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


async def _deliver_magic_link(
    settings: Settings, email: str, application_id: UUID | None
) -> None:
    """Magic-Link-Erstellung/-Versand in eigener Session (Background-Task).

    Läuft **nach** der 202-Antwort → die Antwortzeit ist für Treffer und Nicht-Treffer
    identisch (keine Timing-Enumeration, security.md §1 / §11)."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        await service.request_magic_link(
            db, settings, email=email, application_id=application_id
        )
        await db.commit()


@router.post(
    "/magic-link",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(enforce_auth_payload_limit),
        Depends(rate_limit_magic_link),
        Depends(verify_altcha),
    ],
    # 400 = Altcha ungültig/fehlend, 413 = Body zu groß, 429 = Rate-Limit (api.md §7).
    responses=_errors(400, 413, 429),
)
async def request_magic_link(
    body: MagicLinkRequest, settings: SettingsDep, background: BackgroundTasks
) -> dict[str, str]:
    """Magic-Link anfordern. Anti-Enumeration: **immer** 202 + konstanter Body, kein
    Treffer-Leak. Die DB-Arbeit läuft im Hintergrund → konstante Antwortzeit."""
    background.add_task(
        _deliver_magic_link, settings, str(body.email), body.application_id
    )
    return {"status": "accepted"}


@router.post(
    "/magic-link/verify",
    dependencies=[
        Depends(enforce_auth_payload_limit),
        Depends(rate_limit_magic_link_verify),
    ],
    responses=_errors(400, 410, 413, 429),
)
async def verify_magic_link(
    body: MagicLinkVerifyRequest,
    db: DbSession,
    settings: SettingsDep,
    response: Response,
) -> MagicLinkVerifyOut:
    """Token→Applicant-Session (Scope = genau eine App). Abgelaufen/verbraucht → 410.

    Die Session wird **nur** als HttpOnly-Cookie gesetzt, nie im Body zurückgegeben
    (kein im JS greifbarer Token, security.md §1)."""
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
    return MagicLinkVerifyOut(application_id=UUID(app_id), scope=scope)
