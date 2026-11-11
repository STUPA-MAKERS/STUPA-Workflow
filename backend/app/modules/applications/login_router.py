"""Routes of the applicant login: the magic link and the e-mail login.

The routes keep the prefix `/auth`. They are in `applications` and not in `auth`,
because the applicant login reads applications and starts flow transitions
(§S/backend/python/000649). Each request route answers 202 with a constant body and
does the DB work in the background, so nobody can enumerate addresses by content or by
timing. The session travels only in the HttpOnly cookie.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status

from app.db import get_sessionmaker
from app.deps import DbSession, SettingsDep
from app.modules.applications import email_login, magic_link
from app.modules.applications.mail_data import resolve_application_lang
from app.modules.auth import sessions
from app.modules.auth.schemas import (
    EmailLoginRequest,
    MagicLinkRequest,
    MagicLinkVerifyOut,
    MagicLinkVerifyRequest,
)
from app.modules.flow.dispatch import ActionDispatcher
from app.modules.flow.router import get_action_dispatcher
from app.modules.notifications.provider import mail_queue_from_pool
from app.modules.notifications.service import NotificationService
from app.settings import Settings
from app.shared.antiabuse import (
    enforce_auth_payload_limit,
    rate_limit_magic_link,
    rate_limit_magic_link_verify,
    verify_altcha,
)
from app.shared.errors import (
    ProblemDetail,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Document problem+json for the given error status codes."""
    return dict.fromkeys(codes, _PROBLEM)


async def _deliver_magic_link(
    settings: Settings, email: str, application_id: UUID | None, pool: object
) -> None:
    """Create and send the magic link in its own DB session.

    This runs as a background task after the 202 response. The response time is
    therefore the same for a hit and for a miss, so nobody can enumerate addresses by
    timing. The mail queue delivers the link. Without an arq pool the code logs the
    mail and drops it.

    The mail is in the language of the application that the link opens. A request
    without an application id resolves the same application as the service, so the
    applicant reads the mail in the language they applied in. Only a request that
    matches no application at all falls back to the default language, and that request
    sends no mail.
    """
    queue = mail_queue_from_pool(pool)  # type: ignore[arg-type]
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        app_row = await magic_link.resolve_application(
            db, email=email, application_id=application_id
        )
        lang = await resolve_application_lang(
            db,
            application_id=app_row.id if app_row is not None else None,
            settings=settings,
        )

        async def deliver(recipient: str, link: str) -> None:
            await NotificationService(
                db, queue=queue, settings=settings
            ).send_magic_link(email=recipient, link=link, lang=lang)

        await magic_link.request_magic_link(
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
    responses=_errors(400, 413, 429),
)
async def request_magic_link(
    body: MagicLinkRequest,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
) -> dict[str, str]:
    """Request a magic link.

    The route always answers 202 with a constant body. It never tells the caller if the
    address exists. 400 means that ALTCHA is missing or invalid, 413 that the body is
    too large, 429 the rate limit. The DB work runs in the background to keep the response time
    constant.
    """
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
    dispatcher: Annotated[ActionDispatcher, Depends(get_action_dispatcher)],
) -> MagicLinkVerifyOut:
    """Verify a token and open an applicant session scoped to one application.

    An expired or already used token gives 410.

    The server sets the session only as an HttpOnly cookie. It never returns the token
    in the body, so JavaScript cannot read it.

    The first verify of a guest application starts its flow (automatic transitions,
    task mail) through the flow action dispatcher.
    """
    app_id, token = await magic_link.verify_magic_link(
        db, settings, token=body.token, dispatcher=dispatcher
    )
    await db.commit()
    response.set_cookie(
        settings.applicant_cookie_name,
        token,
        max_age=settings.applicant_session_ttl_hours * 3600,
        **sessions.cookie_kwargs(settings),  # type: ignore[arg-type]
    )
    return MagicLinkVerifyOut(application_id=UUID(app_id))


async def _deliver_email_login(settings: Settings, email: str, pool: object) -> None:
    """Make and send the login link of the e-mail login in its own DB session.

    This runs as a background task after the 202 response, so the response time is the
    same for every address. The link mail is in the language of the newest application
    of the address.
    """
    queue = mail_queue_from_pool(pool)  # type: ignore[arg-type]
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        newest = await magic_link.resolve_application(db, email=email, application_id=None)
        lang = await resolve_application_lang(
            db,
            application_id=newest.id if newest is not None else None,
            settings=settings,
        )
        notifications = NotificationService(db, queue=queue, settings=settings)

        async def send_link(recipient: str, link: str) -> None:
            await notifications.send_email_login(email=recipient, link=link, lang=lang)

        await email_login.request_email_login(
            db, settings, email=email, send_link=send_link
        )
        await db.commit()


@router.post(
    "/email-login",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(enforce_auth_payload_limit),
        Depends(rate_limit_magic_link),
        Depends(verify_altcha),
    ],
    responses=_errors(400, 413, 429),
)
async def request_email_login(
    body: EmailLoginRequest,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
) -> dict[str, str]:
    """Request a login link for every application of an address.

    The route always answers 202 with a constant body, so it never tells whether the
    address has applications. It shares the rate limits of the
    magic-link request. The DB work and the mail run in the background.
    """
    pool = getattr(request.app.state, "arq_pool", None)
    background.add_task(_deliver_email_login, settings, str(body.email), pool)
    return {"status": "accepted"}


@router.post(
    "/email-login/verify",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        Depends(enforce_auth_payload_limit),
        Depends(rate_limit_magic_link_verify),
    ],
    responses=_errors(400, 410, 413, 429),
)
async def verify_email_login(
    body: MagicLinkVerifyRequest,
    db: DbSession,
    settings: SettingsDep,
    response: Response,
    dispatcher: Annotated[ActionDispatcher, Depends(get_action_dispatcher)],
) -> None:
    """Redeem a login link and open an applicant session for its address.

    A used, expired or unknown token gives 410. The session travels only in the
    HttpOnly cookie.
    """
    token = await email_login.verify_email_login(
        db, settings, token=body.token, dispatcher=dispatcher
    )
    await db.commit()
    response.set_cookie(
        settings.applicant_cookie_name,
        token,
        max_age=settings.applicant_session_ttl_hours * 3600,
        **sessions.cookie_kwargs(settings),  # type: ignore[arg-type]
    )
