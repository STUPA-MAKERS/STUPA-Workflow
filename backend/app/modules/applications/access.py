"""Access resolution for application endpoints.

A principal reaches an application route with a session and a permission. An
applicant reaches it with a magic-link token. The token binds to exactly one
``application_id`` and one scope. These dependencies merge both identities into
one `Access` object. They raise 401 without an identity and 403 without
sufficient rights.

`Access.can_see_internal` alone controls internal-comment visibility. Only a
principal gets it. An applicant sees ``public`` comments only.
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
# Global rights: read any application, or edit an application in any flow state.
# The edit right also lifts the state edit lock in the service.
READ_ALL_PERMISSION = "application.read_all"
EDIT_ANY_PERMISSION = "application.edit_any"
# Delete an application permanently. This is a separate, destructive right. An admin
# holds it through the role bypass in `Principal.has`. Any other role holds it only
# through an explicit grant.
DELETE_PERMISSION = "application.delete"


@dataclass(slots=True)
class Access:
    """Resolved access to exactly one application, by a principal or an applicant."""

    application_id: UUID
    principal: Principal | None
    applicant: Applicant | None

    @property
    def can_see_internal(self) -> bool:
        """Tell whether the caller sees internal comments and PII.

        Only a principal does.
        """
        return self.principal is not None

    @property
    def is_owning_applicant(self) -> bool:
        """Tell whether the caller is the magic-link applicant of this application.

        Only this access reads an unconfirmed guest submission
        (``email_confirmed_at IS NULL``) through the item route. A principal and
        the committee scope may not. This mirrors the invisible-in-lists rule.
        """
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
    """Check the principal permission or the applicant scope for the application.

    This function stays public so that adjacent modules reuse the same access
    path. The files module is one example. Its route path carries only the
    ``attachment_id``.

    Raises:
        ForbiddenError: The principal lacks ``perm``, or the magic link does not
            cover this application.
        UnauthorizedError: The request carries neither a principal nor an applicant.
    """
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
    """Check whether this principal created the application while logged in."""
    created_by = await db.scalar(
        select(Application.created_by).where(Application.id == application_id)
    )
    return created_by is not None and created_by == principal.sub


async def _committee_can_read(
    db: AsyncSession, application_id: UUID, principal: Principal
) -> bool:
    """Check the committee read scope for one application.

    The scope grants read access only. It never grants write or transition
    rights. The scope opens in three cases:

    1. The application sits in a cost center whose ``view_gremium_id`` is one of
       the Gremien of the principal. The node or an ancestor may carry the value.
    2. The application is in a ``vote`` state whose ``config.gremiumId`` matches
       one of those Gremien.
    3. A meeting of one of those Gremien voted on the application.

    This mirrors ``ApplicationsService._committee_read_clauses``, the list query.
    Both must cover the same paths. A listed application must open in the detail
    view, and a readable application must appear in the list.
    """
    from app.modules.admin.gremium_roles import gremium_member_ids

    gremien = await gremium_member_ids(db, principal.sub)
    if not gremien:
        return False

    # Case 1 reuses the canonical ancestor logic of the budget tree instead of a
    # second prefix query.
    budget_id = await db.scalar(
        select(Application.budget_id).where(Application.id == application_id)
    )
    if budget_id is not None:
        from app.modules.budget.tree.service import BudgetTreeService

        if await BudgetTreeService(db).can_view_node(budget_id, gremien):
            return True

    # Case 2 evaluates the JSONB config in Python. This stays dialect-neutral,
    # like ``ApplicationsService.list_tasks``.
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

    # Case 3 covers the history: a meeting of a member Gremium voted on it.
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
    """Resolve access like `resolve_access`, and also admit the creator.

    A logged-in principal with ``created_by == principal.sub`` reaches the own
    application without ``perm``.
    """
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
    """Grant read access to one application.

    Four identities pass: a principal with ``application.read``, an applicant
    with ``view`` scope, the logged-in creator, and a committee member in read
    scope. ``application.read_all`` grants global read access. That permission
    ignores the Gremium and the ownership.
    """
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
    """Grant write access to one application.

    Three identities pass: a principal with ``application.manage``, an applicant
    with ``edit`` scope, and the logged-in creator of the own application.

    The service also checks the edit lock (``state.editAllowed``) for every
    identity and answers 409 when the state locks the application.
    ``application.edit_any`` grants write access and lifts that lock.
    """
    if principal is not None and principal.has(EDIT_ANY_PERMISSION):
        return Access(application_id, principal, None)
    return await _resolve_with_creator(
        db, application_id, principal, applicant, perm=MANAGE_PERMISSION, scope="edit"
    )
