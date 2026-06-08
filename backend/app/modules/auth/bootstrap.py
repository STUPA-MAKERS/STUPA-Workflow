"""Bootstrap initialer Admins (#70).

Statte den/die ersten Admin(s) per OIDC-``sub`` **oder** E-Mail mit der ``admin``-Rolle
aus — idempotent, beim OIDC-Login (Callback) und beim Startup-Sweep. Ohne diesen
Mechanismus sperrt sich eine frische, echte OIDC-Installation selbst aus: niemand
besitzt ``admin.*``, also kann auch niemand über ``/admin/role-assignments`` Rollen
vergeben (Henne-Ei).

Die zugewiesene Rolle ist global (kein Gremium-Scope) und unbefristet; ``granted_by``
wird als ``"bootstrap"`` markiert (im Audit/UI sichtbar). Keine PII in Logs
(security.md §1) — nur die Tatsache einer Zuweisung wird geloggt.

Alle DB-Lesungen laufen über ``session.execute`` (keine ``get``/``scalar``-Helfer),
damit die Logik in der Unit-Suite ohne Docker fakebar bleibt (``tests/auth_fakes``).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.models import Role, RoleAssignment
from app.settings import Settings

logger = logging.getLogger("app.auth.bootstrap")

_ADMIN_ROLE_KEY = "admin"
_MEMBER_ROLE_KEY = "member"


def _is_bootstrap_principal(
    row: PrincipalRow, settings: Settings, *, email_verified: bool
) -> bool:
    """``True``, wenn der Principal per ``sub`` oder **verifizierter** E-Mail matcht.

    Der ``sub`` ist die fälschungssichere IdP-Identität und zählt immer. Die E-Mail
    zählt **nur bei ``email_verified``** — sonst könnte ein IdP mit Self-Registration
    ohne Mail-Verifikation einen Token mit beliebiger ``email`` ausstellen (#70).
    """
    if row.sub in settings.bootstrap_admin_subject_set:
        return True
    if not email_verified:
        return False
    email = row.email
    return email is not None and email.lower() in settings.bootstrap_admin_email_set


async def _admin_role_id(db: AsyncSession) -> object | None:
    """ID der ``admin``-Rolle (oder ``None``, wenn Seed/Migration fehlt)."""
    res = await db.execute(select(Role.id).where(Role.key == _ADMIN_ROLE_KEY))
    return res.scalar_one_or_none()


async def _has_admin_assignment(
    db: AsyncSession, principal_id: object, role_id: object
) -> bool:
    """``True``, wenn der Principal die ``admin``-Rolle bereits global (gremium-frei) hält."""
    res = await db.execute(
        select(RoleAssignment.id).where(
            RoleAssignment.principal_id == principal_id,
            RoleAssignment.role_id == role_id,
            RoleAssignment.gremium_id.is_(None),
        )
    )
    return res.scalar_one_or_none() is not None


def _new_assignment(principal_id: object, role_id: object) -> RoleAssignment:
    return RoleAssignment(
        principal_id=principal_id,
        role_id=role_id,
        granted_by="bootstrap",
        valid_from=datetime.now(UTC),
    )


async def ensure_admin_for_principal(
    db: AsyncSession, settings: Settings, row: PrincipalRow, *, email_verified: bool
) -> bool:
    """Login-Pfad: diesem Principal idempotent die ``admin``-Rolle geben.

    Greift nur, wenn der Principal (per ``sub`` oder **verifizierter** E-Mail) in den
    Bootstrap-Listen steht und die Rolle noch nicht (global) hält. ``email_verified``
    stammt aus dem frischen id_token-Claim. Gibt ``True`` bei Neu-Zuweisung.
    **Committet nicht** — der Aufrufer (OIDC-Callback) steuert die Transaktion.
    """
    if not _is_bootstrap_principal(row, settings, email_verified=email_verified):
        return False
    role_id = await _admin_role_id(db)
    if role_id is None:
        logger.warning("bootstrap admin: role %r missing (migrations applied?)", _ADMIN_ROLE_KEY)
        return False
    if await _has_admin_assignment(db, row.id, role_id):
        return False
    db.add(_new_assignment(row.id, role_id))
    await db.flush()
    logger.info("bootstrap admin role granted on login")
    return True


async def _role_id(db: AsyncSession, key: str) -> object | None:
    return (await db.execute(select(Role.id).where(Role.key == key))).scalar_one_or_none()


async def ensure_member_for_principal(db: AsyncSession, row: PrincipalRow) -> bool:
    """Jedem Principal beim Login idempotent die globale ``member``-Rolle geben (#61).

    Alle Benutzer halten **immer** die Basisrolle ``member`` (global, gremium-frei).
    Committet nicht — der Aufrufer steuert die Transaktion."""
    role_id = await _role_id(db, _MEMBER_ROLE_KEY)
    if role_id is None:
        logger.warning("bootstrap member: role %r missing (migrations applied?)", _MEMBER_ROLE_KEY)
        return False
    if await _has_admin_assignment(db, row.id, role_id):  # gleiche Abfrage (global, role_id)
        return False
    db.add(_new_assignment(row.id, role_id))
    await db.flush()
    return True


async def ensure_bootstrap_admins(db: AsyncSession, settings: Settings) -> int:
    """Startup-Sweep: bereits existierenden Principals **per ``sub``** die Rolle geben.

    Bewusst **nur ``sub``** (fälschungssichere IdP-Identität): die gespeicherte
    ``principal.email`` trägt kein ``email_verified``-Flag, also lässt sich beim
    Start nicht prüfen, ob sie verifiziert war (#70). Der E-Mail-Bootstrap greift
    deshalb ausschließlich am Login (``ensure_admin_for_principal`` mit dem frischen,
    verifizierten Claim). Gibt die Anzahl **neuer** Zuweisungen. **Committet nicht.**
    """
    subjects = settings.bootstrap_admin_subject_set
    if not subjects:
        return 0
    role_id = await _admin_role_id(db)
    if role_id is None:
        logger.warning("bootstrap admin sweep: role %r missing", _ADMIN_ROLE_KEY)
        return 0
    res = await db.execute(
        select(PrincipalRow).where(PrincipalRow.sub.in_(subjects))
    )
    granted = 0
    for row in res.scalars().all():
        if not await _has_admin_assignment(db, row.id, role_id):
            db.add(_new_assignment(row.id, role_id))
            granted += 1
    if granted:
        await db.flush()
        logger.info("bootstrap admin sweep granted %d assignment(s)", granted)
    return granted
