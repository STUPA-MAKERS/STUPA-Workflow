"""Bootstrap of initial admins.

Grants the first admin(s), matched by OIDC ``sub`` or email, the ``admin`` role —
idempotently, on OIDC login and in a startup sweep. Without this a fresh OIDC
installation locks itself out: nobody holds ``admin.*``, so nobody can assign
roles (chicken-and-egg). The assignment is global and unlimited; ``granted_by``
is marked ``"bootstrap"``. No PII in logs — only the fact of an assignment.

All DB reads go through ``session.execute`` (no ``get``/``scalar`` helpers) so
the logic stays fakeable in the unit suite without Docker.
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
    """True if the principal matches by ``sub`` or by *verified* email.

    ``sub`` is the forgery-proof IdP identity and always counts. Email counts
    only with ``email_verified`` — otherwise an IdP with self-registration and
    no mail verification could issue a token with an arbitrary ``email``.
    """
    if row.sub in settings.bootstrap_admin_subject_set:
        return True
    if not email_verified:
        return False
    email = row.email
    return email is not None and email.lower() in settings.bootstrap_admin_email_set


async def _admin_role_id(db: AsyncSession) -> object | None:
    """ID of the ``admin`` role (or ``None`` if the seed/migration is missing)."""
    res = await db.execute(select(Role.id).where(Role.key == _ADMIN_ROLE_KEY))
    return res.scalar_one_or_none()


async def _has_admin_assignment(
    db: AsyncSession, principal_id: object, role_id: object
) -> bool:
    """True if the principal already holds the role globally (no gremium scope)."""
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
    """Login path: idempotently grant this principal the ``admin`` role.

    Applies only if the principal is in the bootstrap lists (by ``sub`` or
    verified email) and does not yet hold the role globally. ``email_verified``
    comes from the fresh id_token claim. Returns ``True`` on a new assignment.
    Does not commit — the caller (OIDC callback) owns the transaction.
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
    """Idempotently grant every principal the global ``member`` role on login.

    All users always hold the base role ``member`` (global, no gremium scope).
    Does not commit — the caller owns the transaction."""
    role_id = await _role_id(db, _MEMBER_ROLE_KEY)
    if role_id is None:
        logger.warning("bootstrap member: role %r missing (migrations applied?)", _MEMBER_ROLE_KEY)
        return False
    if await _has_admin_assignment(db, row.id, role_id):  # same query (global, role_id)
        return False
    db.add(_new_assignment(row.id, role_id))
    await db.flush()
    return True


async def ensure_bootstrap_admins(db: AsyncSession, settings: Settings) -> int:
    """Startup sweep: grant the role to existing principals matched by ``sub`` only.

    Deliberately ``sub`` only (forgery-proof IdP identity): the stored
    ``principal.email`` carries no ``email_verified`` flag, so verification
    cannot be checked at startup — email bootstrap happens exclusively at login
    with the fresh claim. Returns the number of new assignments. Does not commit.
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
