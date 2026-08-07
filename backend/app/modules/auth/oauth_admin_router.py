"""Administrative view and kill switch for the OAuth grants of every principal.

`GET /api/oauth/grants` and its siblings are self-service: they show and revoke the
grants of the caller only. That leaves no way to kill a leaked agent token of somebody
else. These two routes close that gap.

**Permission: `admin.users`.** The `/admin/users` page is the user and access
management of the platform. Its holder can already deactivate a principal, which is a
strictly stronger act than killing one of the agent tokens of that principal. So this
route grants no new power, it only makes a finer cut possible. The other candidate keys
do not fit: `mcp.use` is the self-service key that every agent owner holds, `admin.roles`
covers the role DEFINITIONS and not the users, and `privacy.manage` is the GDPR area.
A new permission key would leave the `admin.users` holder with a blind spot on the very
page where the access of a user is managed.

A response never carries a token or a token hash. The database holds SHA-256 hashes
only, and this module maps the row to an explicit schema, so no hash column can leak.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.deps import DbSession, Principal, require_principal
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as record_audit
from app.modules.auth import oauth_service
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.oauth_models import OAuthToken
from app.shared.errors import NotFoundError, ProblemDetail
from app.shared.paging import Page, PageParams

router = APIRouter(prefix="/admin", tags=["admin"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


# The permission gate. It injects the principal, which the audit entry needs as actor.
UsersAdmin = Annotated[Principal, Depends(require_principal("admin.users"))]


class GrantListQuery(PageParams):
    """Query parameters of the grant list: paging plus a filter by principal.

    `extra="forbid"` answers 422 on an unknown parameter instead of ignoring it.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    principal_id: UUID | None = Field(default=None, alias="principalId")


class OAuthGrantAdminOut(BaseModel):
    """One live grant (agent token pair) with its owner.

    `principalName` is the resolved display name or, without one, the email. It is never
    a UUID. `principalId` is there for the filter and for a deep link, not for display.
    The schema holds no token and no token hash.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    principal_id: UUID = Field(alias="principalId")
    principal_name: str | None = Field(alias="principalName")
    principal_email: str | None = Field(alias="principalEmail")
    client_id: str = Field(alias="clientId")
    scope: str
    created_at: datetime = Field(alias="createdAt")
    # `null` means that the token never expires. Only a revoke ends it.
    access_expires_at: datetime | None = Field(alias="accessExpiresAt")
    refresh_expires_at: datetime | None = Field(alias="refreshExpiresAt")


def _to_out(token: OAuthToken, owner: PrincipalRow) -> OAuthGrantAdminOut:
    """Map a token row and its owner to the list item, with the name resolved."""
    return OAuthGrantAdminOut(
        id=token.id,
        principalId=owner.id,
        principalName=owner.display_name or owner.email,
        principalEmail=owner.email,
        clientId=token.client_id,
        scope=token.scope,
        createdAt=token.created_at,
        accessExpiresAt=token.access_expires_at,
        refreshExpiresAt=token.refresh_expires_at,
    )


@router.get(
    "/oauth-grants",
    response_model=Page[OAuthGrantAdminOut],
    responses=_errors(401, 403, 422),
)
async def list_oauth_grants_admin(
    db: DbSession,
    _admin: UsersAdmin,
    query: Annotated[GrantListQuery, Query()],
) -> Page[OAuthGrantAdminOut]:
    """List the live agent tokens of every principal, newest first.

    The list holds the grants that are not revoked. A revoked grant is dead already and
    the audit log keeps its record. The filter `principalId` narrows the list to one
    owner.
    """
    stmt = (
        select(OAuthToken, PrincipalRow)
        .join(PrincipalRow, PrincipalRow.id == OAuthToken.principal_id)
        .where(OAuthToken.revoked_at.is_(None))
    )
    if query.principal_id is not None:
        stmt = stmt.where(OAuthToken.principal_id == query.principal_id)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await db.execute(
            stmt.order_by(OAuthToken.created_at.desc())
            .limit(query.limit)
            .offset(query.offset)
        )
    ).all()
    return Page(
        items=[_to_out(token, owner) for token, owner in rows],
        total=total or 0,
        limit=query.limit,
        offset=query.offset,
    )


@router.delete(
    "/oauth-grants/{grant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_errors(401, 403, 404, 422),
)
async def revoke_oauth_grant_admin(
    grant_id: UUID,
    db: DbSession,
    admin: UsersAdmin,
) -> None:
    """Revoke the grant of any principal, for example after a token leak.

    The call uses the same service function as the self-service revoke, so the access
    token and the refresh token die at once: `resolve_access_token` rejects a revoked
    row on the next request. The audit log records the revoke. A repeated call on an
    already revoked grant changes nothing and writes no second entry.
    """
    row = await oauth_service.load_grant(db, grant_id)
    if row is None:
        raise NotFoundError("Grant not found.")
    if not oauth_service.revoke_grant(row, datetime.now(UTC)):
        return
    # `role_change` is the existing action for every access change that `admin.users`
    # covers (activation, role assignment). The `event` key separates this one in a
    # query. The payload holds id references and metadata, never a token or an email.
    await record_audit(
        db,
        actor=admin.sub,
        action=AuditAction.ROLE_CHANGE,
        target_type="oauth_token",
        target_id=str(row.id),
        data={
            "event": "oauth_grant_revoke",
            "principalId": str(row.principal_id),
            "clientId": row.client_id,
            "scope": row.scope,
        },
    )
    await db.commit()
