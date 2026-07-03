"""Access resolution for application endpoints.

Application routes are reachable either by a principal (session + permission)
or by the applicant (magic-link token bound to exactly one ``application_id``
plus scope). These dependencies unify both identities into an :class:`Access`
object and enforce 401 (no identity) / 403 (insufficient rights).

Internal-comment visibility hangs solely on :attr:`Access.can_see_internal`
(principals only) — applicants see ``public`` comments exclusively.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import DbSession, get_current_applicant, get_current_principal
from app.modules.applications.models import Application
from app.modules.auth.principal import Applicant, ApplicantScope, Principal
from app.shared.errors import ForbiddenError, UnauthorizedError

READ_PERMISSION = "application.read"
MANAGE_PERMISSION = "application.manage"
# Global special rights: read any application, or edit in any flow state
# (the latter also lifts the state edit lock in the service).
READ_ALL_PERMISSION = "application.read_all"
EDIT_ANY_PERMISSION = "application.edit_any"


@dataclass(slots=True)
class Access:
    """Resolved access to exactly one application (principal OR applicant)."""

    application_id: UUID
    principal: Principal | None
    applicant: Applicant | None

    @property
    def can_see_internal(self) -> bool:
        """Only principals see internal comments/PII; applicants never do."""
        return self.principal is not None

    @property
    def is_owning_applicant(self) -> bool:
        """Magic-link applicant of the own application (no principal).

        Only this access may read an unconfirmed guest submission
        (``email_confirmed_at IS NULL``) via the item route — principals/committee
        may not, mirroring the invisible-in-lists semantics."""
        return self.applicant is not None

    @property
    def author_kind(self) -> str:
        return "principal" if self.principal is not None else "applicant"

    @property
    def actor(self) -> str:
        """Audit actor: principal ``sub``, or ``'applicant'``."""
        return self.principal.sub if self.principal is not None else "applicant"


def resolve_access(
    application_id: UUID,
    principal: Principal | None,
    applicant: Applicant | None,
    *,
    perm: str,
    scope: ApplicantScope,
) -> Access:
    """Check principal permission OR applicant scope against the application.

    Public so adjacent modules (e.g. files, whose path only carries the
    ``attachment_id``) reuse the same access path instead of duplicating it."""
    if principal is not None:
        if principal.has(perm):
            return Access(application_id, principal, None)
        raise ForbiddenError(f"Missing permission: {perm}")
    if applicant is not None:
        if str(applicant.application_id) == str(application_id) and applicant.allows(
            scope
        ):
            return Access(application_id, None, applicant)
        raise ForbiddenError("Magic-link does not grant access to this application.")
    raise UnauthorizedError("Authentication required.")


async def _is_creator(db: AsyncSession, application_id: UUID, principal: Principal) -> bool:
    """Check whether this principal is the logged-in creator of the application."""
    created_by = await db.scalar(
        select(Application.created_by).where(Application.id == application_id)
    )
    return created_by is not None and created_by == principal.sub


async def _committee_can_read(
    db: AsyncSession, application_id: UUID, principal: Principal
) -> bool:
    """Check committee read access (read-only, no write/transition rights).

    True if the application sits in a cost centre (node or ancestor) whose
    ``view_gremium_id`` belongs to one of the member's gremien, is currently in
    a ``vote`` state whose ``config.gremiumId`` matches, or was voted on in a
    meeting of one of their gremien.

    Mirrors ``ApplicationsService._committee_read_clauses`` (list query): both
    MUST cover the same paths so a listed application is openable in detail and
    vice versa."""
    from app.modules.admin.gremium_roles import gremium_member_ids

    gremien = await gremium_member_ids(db, principal.sub)
    if not gremien:
        return False

    # (a) Cost centre (node/ancestor) with a view gremium — reuses the budget
    #     tree's canonical ancestor logic instead of duplicating the prefix query.
    budget_id = await db.scalar(
        select(Application.budget_id).where(Application.id == application_id)
    )
    if budget_id is not None:
        from app.modules.budget.tree.service import BudgetTreeService

        if await BudgetTreeService(db).can_view_node(budget_id, gremien):
            return True

    # (b) Current ``vote`` state for one of the gremien (``config.gremiumId``).
    #     JSONB evaluated in Python (dialect-neutral, like ``ApplicationsService.list_tasks``).
    from app.modules.flow.models import State

    row = (
        await db.execute(
            select(State.kind, State.config)
            .join(Application, Application.current_state_id == State.id)
            .where(Application.id == application_id)
        )
    ).first()
    if row is not None and row.kind == "vote":
        cfg = row.config if isinstance(row.config, dict) else {}
        gid = cfg.get("gremiumId")
        if isinstance(gid, str) and gid and UUID(gid) in gremien:
            return True

    # (c) Historical: voted on in a meeting of a member gremium.
    from app.modules.livevote.models import Meeting
    from app.modules.voting.models import Vote

    voted = await db.scalar(
        select(Vote.id)
        .join(Meeting, Meeting.id == Vote.meeting_id)
        .where(Vote.application_id == application_id, Meeting.gremium_id.in_(gremien))
        .limit(1)
    )
    return voted is not None


async def _resolve_with_creator(
    db: AsyncSession,
    application_id: UUID,
    principal: Principal | None,
    applicant: Applicant | None,
    *,
    perm: str,
    scope: ApplicantScope,
) -> Access:
    """Like :func:`resolve_access`, but also admits the logged-in creator
    (``created_by == principal.sub``) without ``perm`` — for their own application."""
    try:
        return resolve_access(application_id, principal, applicant, perm=perm, scope=scope)
    except ForbiddenError:
        if principal is not None and await _is_creator(db, application_id, principal):
            return Access(application_id, principal, None)
        raise


async def require_app_read(
    application_id: UUID,
    db: DbSession,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    applicant: Annotated[Applicant | None, Depends(get_current_applicant)],
) -> Access:
    """Read access: principal with ``application.read``, ``view`` applicant,
    logged-in creator, or committee member in read scope.

    ``application.read_all`` grants global read access regardless of
    gremium/ownership."""
    if principal is not None and principal.has(READ_ALL_PERMISSION):
        return Access(application_id, principal, None)
    try:
        return await _resolve_with_creator(
            db, application_id, principal, applicant, perm=READ_PERMISSION, scope="view"
        )
    except ForbiddenError:
        if principal is not None and await _committee_can_read(
            db, application_id, principal
        ):
            return Access(application_id, principal, None)
        raise


async def require_app_edit(
    application_id: UUID,
    db: DbSession,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    applicant: Annotated[Applicant | None, Depends(get_current_applicant)],
) -> Access:
    """Write access: principal with ``application.manage``, ``edit`` applicant,
    or the logged-in creator of the own application.

    The edit lock (``state.editAllowed``) is additionally checked in the service
    (409) regardless of identity; ``application.edit_any`` grants write access
    and lifts that lock."""
    if principal is not None and principal.has(EDIT_ANY_PERMISSION):
        return Access(application_id, principal, None)
    return await _resolve_with_creator(
        db, application_id, principal, applicant, perm=MANAGE_PERMISSION, scope="edit"
    )
