"""Observers of an application: e-mail addresses that read it and get its status mails.

The rules:

- Only the applicant adds and removes an observer: the logged-in creator, an applicant
  session of the application, and a holder of ``application.manage``
  (`can_manage_observers`). An observer never manages observers.
- An application has at most `MAX_OBSERVERS` observers. An address is there once
  (case-insensitive, CITEXT). The applicant address is no observer, because the
  applicant reads the application anyway.
- The answers never tell whether an address belongs to an account.
- Every add and every removal writes an audit entry with the observer id, never the
  address, because the chain cannot delete a value.
- The end link of a mail carries ``<observer id>.<HMAC>`` (`end_token`). It works
  without a login and dies with the row. The HMAC uses the magic-link pepper, so the
  token needs no column.

Service functions do not commit; the caller owns the transaction.
"""

from __future__ import annotations

import hashlib
import hmac
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.access import (
    MANAGE_PERMISSION,
    Access,
)
from app.modules.applications.models import (
    MAX_OBSERVERS,
    Applicant,
    Application,
    ApplicationObserver,
)
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationProblem

#: The page of the end link. The token rides the fragment, never the query.
END_PATH = "/stop-observing"


def can_manage_observers(access: Access, *, is_creator: bool) -> bool:
    """Tell whether the caller adds and removes the observers of the application.

    The applicant session of the application, the logged-in creator and a holder of
    ``application.manage`` do. An observer never does.
    """
    if access.is_observer:
        return False
    if access.is_owning_applicant:
        return True
    principal = access.principal
    return principal is not None and (is_creator or principal.has(MANAGE_PERMISSION))


def end_token(secret: str, observer_id: UUID) -> str:
    """Return the end-link token of an observer: ``<id>.<HMAC-SHA256 hex>``."""
    digest = hmac.new(secret.encode(), str(observer_id).encode(), hashlib.sha256).hexdigest()
    return f"{observer_id}.{digest}"


def parse_end_token(secret: str, token: str) -> UUID | None:
    """Return the observer id of a valid end-link token, else None."""
    raw_id, _, digest = token.partition(".")
    try:
        observer_id = UUID(raw_id)
    except ValueError:
        return None
    expected = end_token(secret, observer_id).partition(".")[2]
    return observer_id if hmac.compare_digest(expected, digest) else None


def end_link(base_url: str, secret: str, observer_id: UUID) -> str:
    """Return the absolute end link of an observer."""
    return f"{base_url.rstrip('/')}{END_PATH}#t={end_token(secret, observer_id)}"


async def observed_ids(db: AsyncSession, email: str | None) -> frozenset[str]:
    """Return the ids of the applications that the address observes."""
    if not email:
        return frozenset()
    rows = await db.scalars(
        select(ApplicationObserver.application_id).where(ApplicationObserver.email == email)
    )
    return frozenset(str(app_id) for app_id in rows)


async def list_observers(db: AsyncSession, application_id: UUID) -> list[ApplicationObserver]:
    """Return the observers of an application, the oldest first."""
    rows = await db.scalars(
        select(ApplicationObserver)
        .where(ApplicationObserver.application_id == application_id)
        .order_by(ApplicationObserver.added_at, ApplicationObserver.id)
    )
    return list(rows)


def _refused(code: str, msg: str) -> ValidationProblem:
    """Build the 422 of a refused address, on the field ``email``."""
    return ValidationProblem(
        "The observer cannot be added.", code=code, errors=[{"field": "email", "msg": msg}]
    )


async def add_observer(
    db: AsyncSession, application_id: UUID, email: str, *, actor: str
) -> ApplicationObserver:
    """Add an observer and write the audit entry.

    Raises:
        ValidationProblem: The application has `MAX_OBSERVERS` observers
            (``observer_limit``), or the address is the applicant address
            (``observer_is_applicant``).
        ConflictError: The address observes the application already
            (``observer_exists``).
        ForbiddenError: The application is anonymized.
    """
    applicant = (
        await db.execute(
            select(Applicant.email, Applicant.anonymized_at).where(
                Applicant.application_id == application_id
            )
        )
    ).first()
    applicant_email, anonymized_at = applicant if applicant is not None else (None, None)
    if anonymized_at is not None:
        raise ForbiddenError("An anonymized application has no observers.")
    if applicant_email is not None and applicant_email.lower() == email.lower():
        raise _refused("observer_is_applicant", "The applicant reads the application anyway.")
    count = await db.scalar(
        select(func.count())
        .select_from(ApplicationObserver)
        .where(ApplicationObserver.application_id == application_id)
    )
    if (count or 0) >= MAX_OBSERVERS:
        raise _refused("observer_limit", f"An application has at most {MAX_OBSERVERS} observers.")
    exists = await db.scalar(
        select(ApplicationObserver.id).where(
            ApplicationObserver.application_id == application_id,
            ApplicationObserver.email == email,
        )
    )
    if exists is not None:
        raise ConflictError("The address observes the application.", code="observer_exists")
    row = ApplicationObserver(application_id=application_id, email=email, added_by=actor)
    db.add(row)
    await db.flush()
    await audit_record(
        db,
        actor=actor,
        action=AuditAction.APPLICATION_OBSERVER_ADD,
        target_type="application",
        target_id=str(application_id),
        data={"observerId": str(row.id)},
    )
    return row


async def _remove(
    db: AsyncSession, row: ApplicationObserver, *, actor: str, via: str | None
) -> None:
    """Delete one observer row and write the audit entry."""
    application_id = row.application_id
    observer_id = row.id
    await db.delete(row)
    await db.flush()
    await audit_record(
        db,
        actor=actor,
        action=AuditAction.APPLICATION_OBSERVER_REMOVE,
        target_type="application",
        target_id=str(application_id),
        data={"observerId": str(observer_id), **({"via": via} if via else {})},
    )


async def remove_observer(
    db: AsyncSession, application_id: UUID, observer_id: UUID, *, actor: str
) -> None:
    """Remove an observer of the application.

    Raises:
        NotFoundError: The application has no observer with this id.
    """
    row = await db.get(ApplicationObserver, observer_id)
    if row is None or row.application_id != application_id:
        raise NotFoundError("Observer not found.")
    await _remove(db, row, actor=actor, via=None)


async def end_observation(db: AsyncSession, secret: str, token: str) -> None:
    """End an observation through the end link of a mail.

    Raises:
        NotFoundError: The token is invalid, or the observer is gone.
    """
    observer_id = parse_end_token(secret, token)
    row = await db.get(ApplicationObserver, observer_id) if observer_id is not None else None
    if row is None:
        raise NotFoundError("Observer not found.")
    await _remove(db, row, actor="observer", via="endLink")


async def is_creator(db: AsyncSession, application_id: UUID, sub: str) -> bool:
    """Tell whether ``sub`` created the application while logged in."""
    created_by = await db.scalar(
        select(Application.created_by).where(Application.id == application_id)
    )
    return created_by is not None and created_by == sub
