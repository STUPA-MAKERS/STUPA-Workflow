"""Bootstrap of the initial admins.

This module grants the `admin` role to the first admins. It matches them by the OIDC `sub`
or by email. It runs idempotently on OIDC login and in a startup sweep. Without it a fresh
OIDC installation locks itself out. Nobody holds `admin.*`, so nobody can assign a role.
The assignment is global and has no time limit. `granted_by` holds `"bootstrap"`. The logs
carry no PII. They record only the fact of an assignment.

All database reads go through `session.execute` and use no `get` or `scalar` helper. This
keeps the logic fakeable in the unit suite without Docker.
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
    """Return `True` if the principal matches by `sub` or by verified email.

    `sub` is the IdP identity that nobody can forge, so it always counts. An email counts
    only when `email_verified` is true. Otherwise an IdP with self-registration and no mail
    verification could issue a token with an arbitrary `email` claim.
    """
    if row.sub in settings.bootstrap_admin_subject_set:
        return True
    if not email_verified:
        return False
    email = row.email
    return email is not None and email.lower() in settings.bootstrap_admin_email_set


async def _admin_role_id(db: AsyncSession) -> object | None:
    """Return the id of the `admin` role, or `None` if the seed or migration is missing."""
    res = await db.execute(select(Role.id).where(Role.key == _ADMIN_ROLE_KEY))
    return res.scalar_one_or_none()


async def _has_admin_assignment(
    db: AsyncSession, principal_id: object, role_id: object
) -> bool:
    """Return `True` if the principal already holds the role globally, with no Gremium."""
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
    """Grant this principal the `admin` role on the login path.

    The call is idempotent. It applies only when the principal is in the bootstrap lists,
    matched by `sub` or by verified email. It also needs a principal that does not yet hold
    the role globally. The function does not commit. The caller, the OIDC callback, owns
    the transaction. The caller passes the `email_verified` claim of the fresh id_token as
    `email_verified`.

    Returns:
        `True` when the function adds a new assignment.
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
    """Grant every principal the global `member` role on login.

    The call is idempotent. Every user always holds the base role `member`. That role is
    global and has no Gremium scope. The function does not commit. The caller owns the
    transaction.
    """
    role_id = await _role_id(db, _MEMBER_ROLE_KEY)
    if role_id is None:
        logger.warning("bootstrap member: role %r missing (migrations applied?)", _MEMBER_ROLE_KEY)
        return False
    if await _has_admin_assignment(db, row.id, role_id):  # generic query: global + role_id
        return False
    db.add(_new_assignment(row.id, role_id))
    await db.flush()
    return True


async def ensure_bootstrap_admins(db: AsyncSession, settings: Settings) -> int:
    """Grant the `admin` role in a startup sweep to principals matched by `sub`.

    The sweep matches by `sub` only, because `sub` is the IdP identity that nobody can
    forge. The stored `principal.email` carries no `email_verified` flag, so this code
    cannot check the verification at startup. The email bootstrap happens only at login,
    with the fresh claim. The function does not commit.

    Returns:
        The number of new assignments.
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
