"""Auth orchestration.

Binds the primitives (tokens/sessions/oidc/rbac) to DB + settings: magic-link
issue/verify, OIDC callback (code to token to session), principal upsert. Pure
HTTP wiring lives in the router; only domain logic + I/O here.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Applicant as ApplicantRow
from app.modules.applications.models import Application, MagicLink
from app.modules.auth import oidc, sessions, tokens
from app.modules.auth.bootstrap import (
    ensure_admin_for_principal,
    ensure_member_for_principal,
)
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import ApplicantScope
from app.modules.flow.models import State
from app.settings import Settings
from app.shared.errors import ForbiddenError, GoneError

logger = logging.getLogger("app.auth")

# Delivery callback `(email, link)`. Sync or async: production uses an async
# deliver (mail render + arq enqueue); legacy tests use sync lambdas.
Deliver = Callable[[str, str], None | Awaitable[None]]


def _now() -> datetime:
    return datetime.now(UTC)


def _default_deliver(email: str, link: str) -> None:
    """Mail delivery placeholder.

    No token in logs — only the recipient domain is recorded."""
    domain = email.rsplit("@", 1)[-1]
    logger.info("magic-link issued (recipient domain=%s)", domain)


# --- magic link ---
async def _resolve_application(
    db: AsyncSession, *, email: str, application_id: object | None
) -> Application | None:
    """Find the application for (email[, application_id]) via the PII table `applicant`."""
    stmt = (
        select(Application)
        .join(ApplicantRow, ApplicantRow.application_id == Application.id)
        .where(ApplicantRow.email == email)
    )
    if application_id is not None:
        stmt = stmt.where(Application.id == application_id)
    stmt = stmt.order_by(Application.created_at.desc())
    return (await db.execute(stmt)).scalars().first()


async def _scope_for(db: AsyncSession, app: Application) -> ApplicantScope:
    """Edit scope only if the current state is `edit_allowed`; otherwise view."""
    if app.current_state_id is None:
        return "edit"
    state = (
        await db.execute(select(State).where(State.id == app.current_state_id))
    ).scalar_one_or_none()
    if state is not None and state.edit_allowed is False:
        return "view"
    return "edit"


async def request_magic_link(
    db: AsyncSession,
    settings: Settings,
    *,
    email: str,
    application_id: object | None = None,
    deliver: Deliver = _default_deliver,
) -> None:
    """Request a magic link. Sends only on a hit; the caller always answers 202."""
    app = await _resolve_application(db, email=email, application_id=application_id)
    if app is None:
        return  # anti-enumeration: no information to the outside

    scope = await _scope_for(db, app)
    ttl = (
        timedelta(days=settings.magic_link_edit_ttl_days)
        if scope == "edit"
        else timedelta(minutes=settings.magic_link_action_ttl_minutes)
    )
    token = tokens.generate_token()
    db.add(
        MagicLink(
            application_id=app.id,
            token_hash=tokens.hash_token(token, settings.magic_link_secret),
            scope=scope,
            expires_at=_now() + ttl,
            single_use=scope != "edit",
        )
    )
    await db.flush()
    # Token in the URL fragment (#), not the query (?): fragments do not land in
    # Referer headers, server/proxy logs or the browser history query. The
    # frontend reads the fragment and POSTs the token to /auth/magic-link/verify.
    link = f"{settings.public_base_url.rstrip('/')}/antrag/{app.id}#t={token}"
    result = deliver(email, link)
    if inspect.isawaitable(result):
        await result


async def verify_magic_link(
    db: AsyncSession, settings: Settings, *, token: str
) -> tuple[str, ApplicantScope, str]:
    """Verify a token into (`application_id`, scope, applicant session token).

    Invalid/expired/used raises `GoneError` (410). Single-use marks `used_at`."""
    digest = tokens.hash_token(token, settings.magic_link_secret)
    row = (
        await db.execute(select(MagicLink).where(MagicLink.token_hash == digest))
    ).scalar_one_or_none()
    if row is None or not tokens.verify_token_hash(
        token, settings.magic_link_secret, row.token_hash
    ):
        raise GoneError("Magic-Link invalid or expired.")
    now = _now()
    if row.expires_at <= now:
        raise GoneError("Magic-Link expired.")
    if row.single_use:
        # Atomic redemption: only one concurrent verify wins (replay protection).
        # `WHERE used_at IS NULL` serializes at DB level -> 0 rows = already
        # used -> 410.
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
    # Email confirmation: the first successful verify makes a (guest) submission
    # visible and protects it from the 12-hour discard. Idempotent (only while NULL).
    await db.execute(
        update(Application)
        .where(
            Application.id == row.application_id,
            Application.email_confirmed_at.is_(None),
        )
        .values(email_confirmed_at=now)
    )
    scope: ApplicantScope = "edit" if row.scope == "edit" else "view"
    app_id = str(row.application_id)
    # Create a server-side session (instead of a stateless token): the returned
    # opaque `sid` is valid only with an existing `applicant_session` row — a
    # token forged from `SESSION_SECRET` alone does not work.
    expires_at = now + timedelta(hours=settings.applicant_session_ttl_hours)
    session_token = await sessions.create_applicant_session(
        db,
        secret=settings.session_secret,
        application_id=row.application_id,
        scope=scope,
        expires_at=expires_at,
    )
    return app_id, scope, session_token


# --- OIDC ---
async def upsert_principal(db: AsyncSession, claims: oidc.OidcClaims) -> PrincipalRow:
    """Create/update a principal by OIDC `sub` (identity + group cache)."""
    row = (
        await db.execute(select(PrincipalRow).where(PrincipalRow.sub == claims.sub))
    ).scalar_one_or_none()
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
    db: AsyncSession, settings: Settings, *, code: str, verifier: str, nonce: str
) -> tuple[str, PrincipalRow]:
    """Exchange code, verify token, upsert principal, open session; returns (sid, principal)."""
    token_set = await oidc.exchange_code(settings, code=code, verifier=verifier)
    claims = await oidc.verify_id_token(
        settings, id_token=token_set["id_token"], nonce=nonce
    )
    row = await upsert_principal(db, claims)
    # Deactivated principals must not log in — fail-closed at login so no
    # session is created (request resolution blocks them anyway).
    if row.active is False:
        raise ForbiddenError("Account is deactivated.")
    # Bootstrap admins: first/idempotent admin grant at login, otherwise a fresh
    # OIDC installation locks itself out. Email bootstrap counts only with a
    # verified mail claim. The caller commits.
    await ensure_admin_for_principal(
        db, settings, row, email_verified=claims.email_verified
    )
    # Every user always holds the global member role.
    await ensure_member_for_principal(db, row)
    cookie = await sessions.create_principal_session(
        db,
        secret=settings.session_secret,
        principal_id=row.id,
        expires_at=_now() + timedelta(hours=settings.session_ttl_hours),
        refresh_token=token_set.get("refresh_token"),
        id_token=token_set.get("id_token"),
    )
    return cookie, row
