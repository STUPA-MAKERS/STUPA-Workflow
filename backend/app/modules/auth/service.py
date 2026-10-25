"""Auth orchestration.

This module binds the primitives (tokens, sessions, oidc, rbac) to the database and the
settings. It covers the magic-link issue and verify, the OIDC callback (code to token to
session) and the principal upsert.

Pure HTTP wiring lives in the router. This module holds only domain logic and I/O.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.admin.membership_sync import sync_principal_memberships
from app.modules.applications.guest_settings import load_guest_settings
from app.modules.applications.models import Applicant as ApplicantRow
from app.modules.applications.models import Application, MagicLink
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth import oidc, sessions, tokens
from app.modules.auth.bootstrap import (
    ensure_admin_for_principal,
    ensure_member_for_principal,
)
from app.modules.auth.models import SESSION_CLIENT_WEB
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import ApplicantScope
from app.modules.auth.session_renewal import session_expiry
from app.modules.flow.dispatch import ActionDispatcher
from app.modules.flow.service import FlowService
from app.settings import Settings
from app.shared.errors import ForbiddenError, GoneError

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
    stmt = (
        select(Application)
        .join(ApplicantRow, ApplicantRow.application_id == Application.id)
        .where(ApplicantRow.email == email)
    )
    if application_id is not None:
        stmt = stmt.where(Application.id == application_id)
    stmt = stmt.order_by(Application.created_at.desc())
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

    Every new link has `scope = 'edit'` and can be used more than once. The
    session it opens has no fixed scope: each action checks the current state, so
    a locked state still allows a transition with `actorIsApplicant` and an upload.
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
            scope="edit",
            expires_at=expires_at,
            single_use=False,
        )
    )
    await db.flush()
    link = f"{settings.public_base_url.rstrip('/')}/antrag/{app.id}#t={token}"
    result = deliver(email, link)
    if inspect.isawaitable(result):
        await result


async def verify_magic_link(
    db: AsyncSession,
    settings: Settings,
    *,
    token: str,
    dispatcher: ActionDispatcher | None = None,
) -> tuple[str, ApplicantScope, str]:
    """Verify a magic-link token.

    A link without an expiry (`expires_at` NULL) stays valid until a newer link is
    redeemed or the application is archived or anonymized. A single-use token (only
    older rows) gets `used_at` set by an atomic ``UPDATE ... WHERE used_at IS NULL``,
    so only one concurrent verify wins and a replay gets 410.

    The redeem expires every older link of the same application that is still
    valid (`expires_at = now`). An unlimited link therefore does not collect old
    access paths. A newer link that is not yet redeemed stays valid. "Older" includes
    a link with the same creation time, but never this link. The creation time comes
    from the database, so the compare stays in SQL.

    The applicant session is a server-side row, not a stateless token: the opaque
    ``sid`` is valid only with an ``applicant_session`` row, so a token forged from
    ``SESSION_SECRET`` alone does not work.

    The applicant session always has the scope `edit`, also for an old `view`
    link. Each action checks the current state.

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
        The application id, the scope (always `edit`) and the applicant session
        token.

    Raises:
        GoneError: The token is invalid, expired or already used. The router maps this
            to 410.
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
    if row.single_use:
        claimed = (
            await db.execute(
                update(MagicLink)
                .where(MagicLink.id == row.id, MagicLink.used_at.is_(None))
                .values(used_at=now)
                .returning(MagicLink.id)
            )
        ).scalar_one_or_none()
        if claimed is None:
            raise GoneError("Magic-Link already used.")
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
    scope: ApplicantScope = "edit"
    app_id = str(row.application_id)
    expires_at = now + timedelta(hours=settings.applicant_session_ttl_hours)
    session_token = await sessions.create_applicant_session(
        db,
        secret=settings.session_secret,
        application_id=row.application_id,
        scope=scope,
        expires_at=expires_at,
    )
    if confirmed is not None:
        await FlowService(db, dispatcher).start_confirmed(row.application_id)
    return app_id, scope, session_token


async def upsert_principal(db: AsyncSession, claims: oidc.OidcClaims) -> PrincipalRow:
    """Create or update a principal by the OIDC `sub` (identity and group cache).

    Raises:
        ForbiddenError: The `sub` belongs to a principal that an admin merged into
            another one (code `account_merged`). The login fails closed and changes
            nothing: the old row stays a locked reference. It does not log in as the
            new principal either, because only the IdP `sub` of the new principal
            proves that identity.
    """
    row = (
        await db.execute(select(PrincipalRow).where(PrincipalRow.sub == claims.sub))
    ).scalar_one_or_none()
    if row is not None and row.merged_into is not None:
        raise ForbiddenError(
            "This account was merged into another account. Log in with that account.",
            code="account_merged",
        )
    if row is None:
        row = PrincipalRow(sub=claims.sub)
        db.add(row)
    row.email = claims.email
    row.display_name = claims.name
    row.oidc_groups = list(claims.groups)
    row.last_login = _now()
    await db.flush()
    return row


async def oidc_callback(
    db: AsyncSession,
    settings: Settings,
    *,
    code: str,
    verifier: str,
    nonce: str,
    client: str = SESSION_CLIENT_WEB,
) -> tuple[str, PrincipalRow]:
    """Exchange the code, verify the token, upsert the principal and open a session.

    `client` (`web` or `pwa`) selects the session lifetime from `login_settings`.

    A deactivated principal fails closed here, so no session is created. A bootstrap
    admin gets ``admin`` at the first login, because otherwise a fresh OIDC
    installation locks itself out; the email bootstrap counts only with a verified
    mail claim. The gremium memberships follow the OIDC groups that the upsert has
    just cached. One LOGIN audit entry joins the transaction of the session.
    The caller commits.

    Returns:
        The signed `sid` cookie value and the principal row.

    Raises:
        ForbiddenError: The principal is deactivated or merged into another one.
    """
    token_set = await oidc.exchange_code(settings, code=code, verifier=verifier)
    claims = await oidc.verify_id_token(
        settings, id_token=token_set["id_token"], nonce=nonce
    )
    row = await upsert_principal(db, claims)
    if row.active is False:
        raise ForbiddenError("Account is deactivated.")
    await ensure_admin_for_principal(
        db, settings, row, email_verified=claims.email_verified
    )
    await ensure_member_for_principal(db, row)
    await sync_principal_memberships(db, row)
    now = _now()
    cookie = await sessions.create_principal_session(
        db,
        secret=settings.session_secret,
        principal_id=row.id,
        expires_at=await session_expiry(db, client, now),
        refresh_token=token_set.get("refresh_token"),
        id_token=token_set.get("id_token"),
        client=client,
        now=now,
    )
    await audit_record(
        db,
        actor=row.sub,
        action=AuditAction.LOGIN,
        target_type="principal",
        target_id=str(row.id),
        data={"method": "oidc"},
    )
    return cookie, row
