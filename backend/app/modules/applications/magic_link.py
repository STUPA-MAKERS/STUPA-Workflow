"""The magic link of an applicant: issue and verify.

A magic link opens one application for the applicant without an account. The issue
stores only the hash of the token. The verify opens an applicant session scoped to the
application. The first verify of a guest application confirms its address and starts
its flow.

The file is in `applications` and not in `auth`, because it reads applications and
starts flow transitions (§S/backend/python/000649). It stays under full branch coverage
(§S/shared/testing/000046).
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.applications.email_login import assign_to_accounts
from app.modules.applications.guest_settings import load_guest_settings
from app.modules.applications.models import Applicant as ApplicantRow
from app.modules.applications.models import Application, MagicLink
from app.modules.auth import sessions, tokens
from app.modules.flow.dispatch import ActionDispatcher
from app.modules.flow.service import FlowService
from app.settings import Settings
from app.shared.errors import GoneError

logger = logging.getLogger("app.auth")

#: Delivery callback `(email, link)`. It can be sync or async. Production uses an async
#: deliver that renders the mail and enqueues it with arq. Legacy tests use sync lambdas.
Deliver = Callable[[str, str], None | Awaitable[None]]


def _now() -> datetime:
    return datetime.now(UTC)


def _default_deliver(email: str, link: str) -> None:
    """Mail delivery placeholder.

    The log never holds the token. It records only the recipient domain.
    """
    domain = email.rsplit("@", 1)[-1]
    logger.info("magic-link issued (recipient domain=%s)", domain)


async def resolve_application(
    db: AsyncSession, *, email: str, application_id: object | None
) -> Application | None:
    """Find the application for an email and an optional id.

    The lookup goes through the PII table `applicant`. Without an id it takes the
    newest application of that address, which is the one the magic link opens. The
    router uses the same function to read the language of that application.
    """
    by_email = (
        select(Application)
        .join(ApplicantRow, ApplicantRow.application_id == Application.id)
        .where(ApplicantRow.email == email)
    )
    narrowed = (
        by_email if application_id is None else by_email.where(Application.id == application_id)
    )
    stmt = narrowed.order_by(Application.created_at.desc())
    return (await db.execute(stmt)).scalars().first()


async def request_magic_link(
    db: AsyncSession,
    settings: Settings,
    *,
    email: str,
    application_id: object | None = None,
    deliver: Deliver = _default_deliver,
) -> None:
    """Request a magic link.

    The function sends a mail only on a hit. The caller always answers 202, so the
    outside learns nothing about the address (anti-enumeration).

    The token goes into the URL fragment (``#``), not into the query, because a
    fragment does not land in a Referer header, in a server or proxy log, or in the
    browser history. The frontend reads the fragment and POSTs the token to
    ``/auth/magic-link/verify``.

    A link can be used more than once. The session it opens has no scope: each
    action checks the current state, so a locked state still allows a transition
    with `actorIsApplicant` and an upload.
    The data lock stays the 409 of the edit service.

    The lifetime comes from `guest_application_settings.link_ttl_days`. NULL gives
    a link without an expiry. A request expires no other link. Otherwise anybody
    who knows the address could cut off the applicant. The redeem does that.
    """
    app = await resolve_application(db, email=email, application_id=application_id)
    if app is None:
        return

    link_ttl_days = (await load_guest_settings(db)).link_ttl_days
    expires_at = (
        _now() + timedelta(days=link_ttl_days) if link_ttl_days is not None else None
    )
    token = tokens.generate_token()
    db.add(
        MagicLink(
            application_id=app.id,
            token_hash=tokens.hash_token(token, settings.magic_link_secret),
            expires_at=expires_at,
        )
    )
    await db.flush()
    link = f"{settings.public_base_url.rstrip('/')}/my-applications/{app.id}#t={token}"
    result = deliver(email, link)
    if inspect.isawaitable(result):
        await result


async def verify_magic_link(
    db: AsyncSession,
    settings: Settings,
    *,
    token: str,
    dispatcher: ActionDispatcher | None = None,
) -> tuple[str, str]:
    """Verify a magic-link token.

    A link without an expiry (`expires_at` NULL) stays valid until a newer link is
    redeemed or the application is archived or anonymized.

    The redeem expires every older link of the same application that is still
    valid (`expires_at = now`). An unlimited link therefore does not collect old
    access paths. A newer link that is not yet redeemed stays valid. "Older" includes
    a link with the same creation time, but never this link. The creation time comes
    from the database, so the compare stays in SQL.

    The applicant session is a server-side row, not a stateless token: the opaque
    ``sid`` is valid only with an ``applicant_session`` row, so a token forged from
    ``SESSION_SECRET`` alone does not work.

    The first verify of a guest application confirms its email. That makes the
    submission visible and protects it from the discard after ``confirm_ttl_hours``.
    The update runs only while the column is NULL, so of two concurrent verifies only
    one gets the row back. The application
    then leaves its rest in the flow: `FlowService.start_confirmed` runs the
    automatic transitions and sends the task mail. `dispatcher` sends the mails
    and the other flow actions. The start commits the session. A later verify
    finds the email confirmed and starts nothing, so a second click sends no
    second mail.

    Returns:
        The application id and the applicant session token.

    Raises:
        GoneError: The token is invalid or expired. The router maps this to 410.
    """
    digest = tokens.hash_token(token, settings.magic_link_secret)
    row = (
        await db.execute(select(MagicLink).where(MagicLink.token_hash == digest))
    ).scalar_one_or_none()
    if row is None or not tokens.verify_token_hash(
        token, settings.magic_link_secret, row.token_hash
    ):
        raise GoneError("Magic-Link invalid or expired.")
    now = _now()
    if row.expires_at is not None and row.expires_at <= now:
        raise GoneError("Magic-Link expired.")
    confirmed = (
        await db.execute(
            update(Application)
            .where(
                Application.id == row.application_id,
                Application.email_confirmed_at.is_(None),
            )
            .values(email_confirmed_at=now)
            .returning(Application.id)
        )
    ).scalar_one_or_none()
    redeemed = aliased(MagicLink)
    redeemed_at = (
        select(redeemed.created_at).where(redeemed.id == row.id).scalar_subquery()
    )
    await db.execute(
        update(MagicLink)
        .where(
            MagicLink.application_id == row.application_id,
            MagicLink.id != row.id,
            MagicLink.created_at <= redeemed_at,
            or_(MagicLink.expires_at.is_(None), MagicLink.expires_at > now),
        )
        .values(expires_at=now)
    )
    app_id = str(row.application_id)
    expires_at = now + timedelta(hours=settings.applicant_session_ttl_hours)
    session_token = await sessions.create_applicant_session(
        db,
        secret=settings.session_secret,
        application_id=row.application_id,
        expires_at=expires_at,
    )
    if confirmed is not None:
        await assign_to_accounts(db, [row.application_id])
        await FlowService(db, dispatcher).start_confirmed(row.application_id)
    return app_id, session_token
