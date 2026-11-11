"""Auth endpoints.

This module holds the OIDC login and callback (auth code plus PKCE), the
server-session cookie, the magic-link issue and verify routes, `/auth/me` and logout.

A token never reaches JavaScript or the response body. The server sends it only in an
HttpOnly+Secure+SameSite=Lax cookie.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.deps import DbSession, SettingsDep
from app.modules.auth import oidc, service, sessions
from app.modules.auth.login_settings import load_login_settings, session_days
from app.modules.auth.models import SESSION_CLIENT_WEB, AuthSession
from app.modules.auth.oidc import OidcError, OidcUnavailableError
from app.modules.auth.schemas import (
    LogoutOut,
)
from app.settings import Settings
from app.shared.errors import (
    BadRequestError,
    ForbiddenError,
    NotFoundError,
    ProblemDetail,
    ServiceUnavailableError,
)

logger = logging.getLogger("app.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}
#: OIDC transaction: 10-minute window from authorize to callback.
_TX_MAX_AGE = 600


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Document problem+json for the given error status codes."""
    return dict.fromkeys(codes, _PROBLEM)


@router.get(
    "/login",
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    responses=_errors(404, 503),
)
async def login(
    settings: SettingsDep,
    client: Annotated[Literal["web", "pwa"], Query()] = SESSION_CLIENT_WEB,
    return_to: Annotated[str | None, Query(alias="returnTo", max_length=2048)] = None,
) -> RedirectResponse:
    """Redirect to the IdP with the auth code flow and PKCE.

    The tx cookie carries the state, the code verifier, the nonce and the client. The
    authorize endpoint comes from the discovery document of the IdP. If that document
    is unusable, the route answers 503.

    `client=pwa` comes from the installed app (display mode standalone). The session
    then gets the lifetime of the app (`login_settings.pwa_session_days`), else that
    of a browser tab. The value only selects a lifetime; both stay bounded by the
    admin settings and the check at the IdP.

    `returnTo` is the path of the app where the login started. The callback sends the
    browser back there. A value that is not a same-origin path of the app
    (`sessions.safe_return_to`) is dropped, and the callback goes to the home page.
    """
    if not settings.oidc_enabled:
        raise NotFoundError("OIDC is not configured.")
    verifier, challenge = oidc.generate_pkce()
    state = oidc.generate_state()
    nonce = oidc.generate_nonce()
    try:
        url = await oidc.authorization_url(
            settings, state=state, challenge=challenge, nonce=nonce
        )
    except OidcError as exc:
        raise ServiceUnavailableError("The identity provider is unavailable.") from exc
    response = RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    response.set_cookie(
        settings.oidc_tx_cookie_name,
        sessions.issue_oidc_tx(
            settings.session_secret,
            state,
            verifier,
            nonce,
            client,
            sessions.safe_return_to(return_to),
        ),
        max_age=_TX_MAX_AGE,
        **sessions.cookie_kwargs(settings),  # type: ignore[arg-type]
    )
    return response


def _callback_destination(
    settings: Settings, *, return_to: str | None, oauth_in_flight: bool
) -> str:
    """Return the page after the login: the OAuth code-mint step, `return_to` or home."""
    base = settings.public_base_url.rstrip("/")
    return (
        base + "/api/oauth/finish"
        if oauth_in_flight
        else (base + return_to if return_to else settings.public_base_url)
    )


@router.get(
    "/callback",
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    responses=_errors(400, 404, 503),
)
async def callback(
    request: Request,
    db: DbSession,
    settings: SettingsDep,
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
) -> RedirectResponse:
    """Exchange the code for a token and open a session.

    The state match and the nonce in the id_token protect against CSRF and replay. An
    IdP that cannot be reached gives 503. A rejected code or token gives 400.

    A login with the ``sub`` of a merged account redirects to the start page, which
    says what happened, instead of a raw 403; nothing is committed and the OIDC
    transaction ends. Otherwise the route commits the principal and the session row,
    because ``get_session`` never commits. With an OAuth login in flight
    (``ap_oauth_tx``) it redirects to the code-mint step, else to the page where the
    login started. Both targets are same-origin, so there is no open redirect.
    """
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
            db,
            settings,
            code=code,
            verifier=tx["verifier"],
            nonce=tx["nonce"],
            client=tx["client"],
        )
    except OidcUnavailableError as exc:
        raise ServiceUnavailableError("The identity provider is unavailable.") from exc
    except OidcError as exc:
        raise BadRequestError("OIDC login failed.") from exc
    except ForbiddenError as exc:
        if exc.code != "account_merged":
            raise
        await db.rollback()
        merged = settings.public_base_url.rstrip("/") + "/?loginError=account_merged"
        refused = RedirectResponse(merged, status_code=status.HTTP_303_SEE_OTHER)
        refused.delete_cookie(settings.oidc_tx_cookie_name, path="/")
        return refused
    await db.commit()

    dest = _callback_destination(
        settings,
        return_to=tx.get("return_to"),
        oauth_in_flight=bool(request.cookies.get(settings.oauth_tx_cookie_name)),
    )
    days = session_days(await load_login_settings(db), tx["client"])
    response = RedirectResponse(dest, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    response.set_cookie(
        settings.session_cookie_name,
        cookie,
        max_age=days * 24 * 3600,
        **sessions.cookie_kwargs(settings),  # type: ignore[arg-type]
    )
    response.delete_cookie(settings.oidc_tx_cookie_name, path="/")
    return response


async def _idp_logout_url(settings: Settings, ended: AuthSession | None) -> str | None:
    """Return the RP-initiated logout URL of the IdP for an ended session, if there is one.

    A failed discovery gives `None`, because the local logout must not fail on an IdP
    outage.
    """
    if not settings.oidc_enabled or ended is None:
        return None
    try:
        return await oidc.end_session_url(settings, id_token=ended.id_token)
    except OidcError:
        logger.warning("oidc discovery failed at logout, no IdP logout URL")
        return None


@router.post("/logout")
async def logout(
    request: Request, db: DbSession, settings: SettingsDep, response: Response
) -> LogoutOut:
    """End the server sessions and clear the cookies.

    The route is idempotent. It ends the principal session and any applicant session.

    Returns:
        For OIDC, the RP-initiated logout URL (the `end_session_endpoint` of the IdP
        with `id_token_hint`). The frontend must send the browser there to end the IdP
        SSO session. Without that step the SSO login survives. The URL is `None` when
        the IdP has no such endpoint or its discovery document is unusable. The local
        sessions end in every case, because a logout that fails on an IdP outage would
        leave the session open.
    """
    cookie = request.cookies.get(settings.session_cookie_name)
    ended = (
        await sessions.delete_principal_session(
            db,
            secret=settings.session_secret,
            cookie_value=cookie,
            max_age=sessions.SESSION_COOKIE_MAX_AGE,
        )
        if cookie
        else None
    )
    logout_url = await _idp_logout_url(settings, ended)
    ap_cookie = request.cookies.get(settings.applicant_cookie_name)
    if ap_cookie:
        await sessions.delete_applicant_session(
            db,
            secret=settings.session_secret,
            cookie_value=ap_cookie,
            max_age=settings.applicant_session_ttl_hours * 3600,
        )
    await db.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.applicant_cookie_name, path="/")
    return LogoutOut(logout_url=logout_url)
