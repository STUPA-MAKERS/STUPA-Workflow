"""Auth-Orchestrierung (security.md §1/§2, api.md §1/§3).

Bindet die Primitive (tokens/sessions/oidc/rbac) an DB + Settings:
Magic-Link issue/verify, OIDC-Callback (Code→Token→Session), Principal-Upsert.
Reine HTTP-Verdrahtung liegt im Router; hier nur Domänenlogik + I/O.
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

# Versand-Callback `(email, link)`. Sync **oder** async: T-18 liefert einen
# async-Deliver (Mail-Render + arq-Enqueue); Bestands-Tests nutzen sync-Lambdas.
Deliver = Callable[[str, str], None | Awaitable[None]]


def _now() -> datetime:
    return datetime.now(UTC)


def _default_deliver(email: str, link: str) -> None:
    """Mail-Versand-Platzhalter (echtes SMTP/Templating: T-18).

    **Kein Token in Logs** (security.md §1) — nur Empfänger-Domain wird vermerkt."""
    domain = email.rsplit("@", 1)[-1]
    logger.info("magic-link issued (recipient domain=%s)", domain)


# --------------------------------------------------------------------------- #
# Magic-Link
# --------------------------------------------------------------------------- #
async def _resolve_application(
    db: AsyncSession, *, email: str, application_id: object | None
) -> Application | None:
    """Antrag zu (Mail[, application_id]) finden — über die PII-Tabelle `applicant`."""
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
    """Edit-Scope nur, wenn der aktuelle State `edit_allowed` ist; sonst view."""
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
    """Magic-Link anfordern. Versendet nur bei Treffer; Aufrufer antwortet **immer** 202."""
    app = await _resolve_application(db, email=email, application_id=application_id)
    if app is None:
        return  # Anti-Enumeration: keine Auskunft nach außen.

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
    # Token im URL-Fragment (#), nicht im Query (?): Fragmente landen nicht in
    # Referer-Headern, Server-/Proxy-Logs oder der Browser-History-Query (security.md §1).
    # Das FE liest das Fragment und sendet den Token per POST an /auth/magic-link/verify.
    link = f"{settings.public_base_url.rstrip('/')}/antrag/{app.id}#t={token}"
    result = deliver(email, link)
    if inspect.isawaitable(result):
        await result


async def verify_magic_link(
    db: AsyncSession, settings: Settings, *, token: str
) -> tuple[str, ApplicantScope, str]:
    """Token verifizieren → (`application_id`, scope, Applicant-Session-Token).

    Ungültig/abgelaufen/verbraucht → `GoneError` (410). Single-use markiert `used_at`."""
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
        # Atomare Einlösung: nur eine nebenläufige Verify gewinnt (Replay-Schutz).
        # `WHERE used_at IS NULL` serialisiert auf DB-Ebene → 0 Zeilen = schon
        # verbraucht → 410 (security.md §1).
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
    scope: ApplicantScope = "edit" if row.scope == "edit" else "view"
    app_id = str(row.application_id)
    session_token = sessions.issue_applicant_token(settings.session_secret, app_id, scope)
    return app_id, scope, session_token


# --------------------------------------------------------------------------- #
# OIDC
# --------------------------------------------------------------------------- #
async def upsert_principal(db: AsyncSession, claims: oidc.OidcClaims) -> PrincipalRow:
    """Principal per OIDC-`sub` anlegen/aktualisieren (Identität + Gruppen-Cache)."""
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
    """Code→Token→verify→Principal-Upsert→Server-Session. Gibt (sid-Cookie, Principal)."""
    token_set = await oidc.exchange_code(settings, code=code, verifier=verifier)
    claims = await oidc.verify_id_token(
        settings, id_token=token_set["id_token"], nonce=nonce
    )
    row = await upsert_principal(db, claims)
    # Deaktivierte Principals (#30) dürfen sich nicht anmelden — fail-closed schon
    # beim Login, damit keine Session entsteht (die Request-Auflösung blockt sie
    # ohnehin, vgl. deps.get_current_principal).
    if not row.active:
        raise ForbiddenError("Account is deactivated.")
    # Bootstrap-Admins (#70): erstmaliger/idempotenter admin-Grant beim Login, sonst
    # sperrt sich eine frische OIDC-Installation selbst aus. Der E-Mail-Bootstrap zählt
    # nur bei verifizierter Mail (claims.email_verified). Committet der Aufrufer.
    await ensure_admin_for_principal(
        db, settings, row, email_verified=claims.email_verified
    )
    # Jeder Benutzer hält immer die globale member-Rolle (#61).
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
