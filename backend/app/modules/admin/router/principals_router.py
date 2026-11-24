"""Admin routes of the persons: list, change, merge and group revoke."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query, Request

from app.deps import SettingsDep
from app.modules.admin.router.deps import (
    _PRINCIPAL_READERS,
    DelegationMailerDep,
    MergeAdmin,
    MergeServiceDep,
    RevokeAdmin,
    RevokeServiceDep,
    ServiceDep,
    UsersAdmin,
    _errors,
)
from app.modules.admin.schemas import (
    MergePreviewOut,
    MergeResultOut,
    PrincipalMergeIn,
    PrincipalOut,
    PrincipalRevokeIn,
    PrincipalUpdate,
    RevokePreviewOut,
    RevokeResultOut,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get(
    "/principals",
    response_model=list[PrincipalOut],
    dependencies=[_PRINCIPAL_READERS],
    responses=_errors(401, 403),
)
async def list_principals(
    service: ServiceDep,
    q: Annotated[str | None, Query()] = None,
    last_login_before: Annotated[date | None, Query(alias="lastLoginBefore")] = None,
    include_never: Annotated[bool, Query(alias="includeNever")] = False,
    has_groups: Annotated[bool | None, Query(alias="hasGroups")] = None,
) -> list[PrincipalOut]:
    """List or search the users (OIDC principals) by `sub`, name or e-mail.

    `lastLoginBefore` (ISO date) keeps the people whose last login is before that day;
    `includeNever=true` adds the people who never logged in (alone: only those).
    `hasGroups` keeps the people with (true) or without (false) OIDC groups.
    """
    return await service.search_principals(
        q,
        last_login_before=last_login_before,
        include_never=include_never,
        has_groups=has_groups,
    )


@router.patch(
    "/principals/{principal_id}",
    response_model=PrincipalOut,
    responses=_errors(401, 403, 404, 422),
)
async def patch_principal(
    principal_id: UUID, payload: PrincipalUpdate, service: ServiceDep, principal: UsersAdmin
) -> PrincipalOut:
    """Activate or deactivate a user."""
    return await service.set_principal_active(principal_id, payload.active, principal.sub)


@router.get(
    "/principals/{principal_id}/merge-preview",
    response_model=MergePreviewOut,
    responses=_errors(401, 403, 404, 409, 422),
)
async def preview_principal_merge(
    principal_id: UUID,
    service: MergeServiceDep,
    admin: MergeAdmin,
    target_id: Annotated[UUID, Query(alias="targetId")],
) -> MergePreviewOut:
    """Show what a merge of this (old) account into `targetId` would do.

    The answer counts per area the rows that the merge rewrites, combines and removes,
    and lists the real conflicts that block it. It writes nothing.
    """
    return await service.preview(principal_id, target_id, actor=admin.sub)


@router.post(
    "/principals/{principal_id}/merge",
    response_model=MergeResultOut,
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def merge_principal(
    principal_id: UUID,
    payload: PrincipalMergeIn,
    service: MergeServiceDep,
    admin: MergeAdmin,
) -> MergeResultOut:
    """Merge this (old) account into `targetId` in one transaction.

    The merge rewrites the references, combines harmless duplicates and locks the old
    account as a reference to the new one. A real conflict gives 409 `merge_conflict`
    and changes nothing. The audit log stays as it is; the merge itself is the audit
    action `principal_merge`.
    """
    return await service.merge(principal_id, payload.target_id, actor=admin.sub)


@router.get(
    "/principals/{principal_id}/revoke-preview",
    response_model=RevokePreviewOut,
    responses=_errors(401, 403, 404, 409),
)
async def preview_principal_revoke(
    principal_id: UUID, service: RevokeServiceDep, admin: RevokeAdmin
) -> RevokePreviewOut:
    """Show per Gremium and per global role what the person has. Writes nothing.

    Per Gremium: the membership and the gremium role with the SSO groups that cause
    them, the manual role assignments, the pool entries, the delegations in planned
    meetings (revoked) and in live meetings (kept), and the open votes. Each SSO group
    lists every Gremium and global role it leads to.
    """
    return await service.preview(principal_id, actor=admin.sub)


@router.post(
    "/principals/{principal_id}/revoke",
    response_model=RevokeResultOut,
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def revoke_principal(
    principal_id: UUID,
    payload: PrincipalRevokeIn,
    service: RevokeServiceDep,
    admin: RevokeAdmin,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    mailer: DelegationMailerDep,
) -> RevokeResultOut:
    """Clear the selected Gremien completely and remove the selected global roles.

    One transaction. A removed SSO group that also leads to an entry that is not
    selected gives 422 `revoke_incomplete`. The own account gives 409
    `revoke_own_account`. The other side of each revoked delegation gets the usual
    mail: the delegate, or the delegator when the person was the delegate.
    """
    out, mails = await service.revoke(principal_id, payload, actor=admin.sub)
    pool = getattr(request.app.state, "arq_pool", None)
    for info in mails:
        background.add_task(mailer.delegation_changed, settings, info, granted=False, pool=pool)
    return out
