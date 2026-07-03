"""Auth endpoints.

OIDC login/callback (Keycloak, auth code + PKCE), server-session cookie,
magic-link issue/verify, `/auth/me`, logout. Tokens never reach JS or the body —
HttpOnly+Secure+SameSite=Lax cookies only.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.db import get_sessionmaker
from app.deps import DbSession, Principal, SettingsDep, require_principal
from app.modules.admin.models import Gremium
from app.modules.auth import oidc, service, sessions
from app.modules.auth.oidc import OidcError
from app.modules.auth.schemas import (
    GremiumRef,
    LogoutOut,
    MagicLinkRequest,
    MagicLinkVerifyOut,
    MagicLinkVerifyRequest,
    MeOut,
)
from app.modules.notifications.provider import mail_queue_from_pool
from app.modules.notifications.service import NotificationService
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
_TX_MAX_AGE = 600  # OIDC transaction: 10-minute window authorize -> callback.


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Document problem+json for the given error status codes."""
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
    """Redirect to Keycloak (auth code + PKCE); state/verifier/nonce in the tx cookie."""
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
    """Code to token to session. CSRF/replay protection via state match + nonce in the id_token."""
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
    # Persist principal + auth_session (get_session never commits itself);
    # without a commit the request close would roll both rows back.
    await db.commit()

    # If an OAuth AS login is in flight (MCP, ap_oauth_tx set), continue to the
    # code-mint step instead of the app home (same-origin, no open redirect).
    dest = settings.public_base_url
    if request.cookies.get(settings.oauth_tx_cookie_name):
        dest = settings.public_base_url.rstrip("/") + "/api/oauth/finish"
    response = RedirectResponse(dest, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
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
    """End the server session(s) and clear cookies (idempotent). Ends both the
    principal and any applicant session. For OIDC, returns the RP-initiated
    logout URL (Keycloak `end_session`, id_token_hint) so the frontend also
    ends the IdP SSO session — otherwise the SSO login survives."""
    logout_url: str | None = None
    cookie = request.cookies.get(settings.session_cookie_name)
    if cookie:
        ended = await sessions.delete_principal_session(
            db,
            secret=settings.session_secret,
            cookie_value=cookie,
            max_age=settings.session_ttl_hours * 3600,
        )
        if settings.oidc_enabled and ended is not None:
            logout_url = oidc.end_session_url(settings, id_token=ended.id_token)
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


@router.get("/me", responses=_errors(401, 403))
async def me(
    principal: Annotated[Principal, Depends(require_principal())],
    db: DbSession,
) -> MeOut:
    """Return the principal plus resolved roles/permissions/groups and own gremien."""
    return MeOut(
        sub=principal.sub,
        email=principal.email,
        display_name=principal.display_name,
        roles=sorted(principal.roles),
        permissions=sorted(principal.permissions),
        groups=sorted(principal.groups),
        gremien=await _gremien_for(db, principal.sub),
        session_manage_gremien=await _session_manage_gremien(db, principal.sub),
        has_scoped_budget_view=await _has_scoped_budget_view(db, principal.sub),
        in_substitute_pool=await _in_substitute_pool(db, principal.sub),
    )


async def _in_substitute_pool(db: DbSession, sub: str) -> bool:
    """Is ``sub`` in at least one substitute pool? Frontend gating of the
    meeting timeline for pool substitutes without own membership."""
    from app.modules.auth.models import Principal as PrincipalRow
    from app.modules.delegations.models import DelegationSubstitute

    pid_subq = select(PrincipalRow.id).where(PrincipalRow.sub == sub).scalar_subquery()
    hit = await db.scalar(
        select(DelegationSubstitute.id)
        .where(DelegationSubstitute.substitute_principal_id == pid_subq)
        .limit(1)
    )
    return hit is not None


async def _has_scoped_budget_view(db: DbSession, sub: str) -> bool:
    """Does a member gremium of the principal own a cost centre as visibility
    root? Frontend gating of the budget tab."""
    from app.modules.admin.gremium_roles import gremium_member_ids
    from app.modules.budget.tree_models import Budget

    member = await gremium_member_ids(db, sub)
    if not member:
        return False
    hit = await db.scalar(
        select(Budget.id).where(Budget.view_gremium_id.in_(member)).limit(1)
    )
    return hit is not None


async def _session_manage_gremien(db: DbSession, sub: str) -> list[UUID]:
    """Gremien ``sub`` manages via their gremium role (``session.manage``).

    Same source as ``MeetingService.can_manage`` — frontend gating ("create
    meeting") and server decision stay congruent."""
    from app.modules.admin.gremium_roles import gremium_ids_with_permission

    return sorted(
        await gremium_ids_with_permission(db, sub, "session.manage"), key=str
    )


async def _gremien_for(db: DbSession, sub: str) -> list[GremiumRef]:
    """Gremien ``sub`` is a member of (valid ``gremium_membership``).

    Uses the same source as the server-side visibility logic
    (``gremium_member_ids``) so frontend gating and server filters agree. The
    global ``role_assignment`` member role has ``gremium_id = NULL`` and is NOT
    a gremium membership. Magic-link applicants get an empty list.
    """
    from app.modules.admin.gremium_roles import gremium_member_ids

    ids = await gremium_member_ids(db, sub)
    if not ids:
        return []
    rows = (
        await db.execute(
            select(Gremium.id, Gremium.name, Gremium.slug)
            .where(Gremium.id.in_(ids))
            .order_by(Gremium.name)
        )
    ).all()
    return [GremiumRef(id=r.id, name=r.name, slug=r.slug) for r in rows]


async def _deliver_magic_link(
    settings: Settings, email: str, application_id: UUID | None, pool: object
) -> None:
    """Create/send the magic link in its own session (background task).

    Runs after the 202 response, so response time is identical for hit and
    miss (no timing enumeration). Delivery goes through the mail queue; without
    an arq pool it is logged and dropped."""
    queue = mail_queue_from_pool(pool)  # type: ignore[arg-type]
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:

        async def deliver(recipient: str, link: str) -> None:
            await NotificationService(
                db, queue=queue, settings=settings
            ).send_magic_link(email=recipient, link=link)

        await service.request_magic_link(
            db, settings, email=email, application_id=application_id, deliver=deliver
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
    # 400 = ALTCHA invalid/missing, 413 = body too large, 429 = rate limit.
    responses=_errors(400, 413, 429),
)
async def request_magic_link(
    body: MagicLinkRequest,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
) -> dict[str, str]:
    """Request a magic link. Anti-enumeration: always 202 with a constant body,
    no hit leak. DB work runs in the background for constant response time."""
    pool = getattr(request.app.state, "arq_pool", None)
    background.add_task(
        _deliver_magic_link, settings, str(body.email), body.application_id, pool
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
    """Verify a token into an applicant session (scoped to one application); expired/used -> 410.

    The session is set only as an HttpOnly cookie, never returned in the body
    (no token reachable from JS)."""
    app_id, scope, token = await service.verify_magic_link(
        db, settings, token=body.token
    )
    await db.commit()
    response.set_cookie(
        settings.applicant_cookie_name,
        token,
        max_age=settings.applicant_session_ttl_hours * 3600,
        **_cookie_kwargs(settings),  # type: ignore[arg-type]
    )
    return MagicLinkVerifyOut(application_id=UUID(app_id), scope=scope)
