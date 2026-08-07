"""Administrative view and kill switch for the OAuth grants of every principal.

`/api/oauth/grants` is self-service and reaches the grants of the caller only. These
two routes let an `admin.users` holder kill a leaked agent token of somebody else.
A response never carries a token or a token hash.
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


UsersAdmin = Annotated[Principal, Depends(require_principal("admin.users"))]


class GrantListQuery(PageParams):
    """Query parameters of the grant list: paging plus a filter by principal."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    principal_id: UUID | None = Field(default=None, alias="principalId")


class OAuthGrantAdminOut(BaseModel):
    """One live grant (agent token pair) with its owner. Holds no token and no hash."""

    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    principal_id: UUID = Field(alias="principalId")
    principal_name: str | None = Field(alias="principalName")
    principal_email: str | None = Field(alias="principalEmail")
    client_id: str = Field(alias="clientId")
    scope: str
    created_at: datetime = Field(alias="createdAt")
    # `null` = never expires; only a revoke ends it.
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

    Revoked grants stay out; `principalId` narrows the list to one owner.
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

    The access token and the refresh token die at once. A repeated call is a no-op.
    """
    row = await oauth_service.load_grant(db, grant_id)
    if row is None:
        raise NotFoundError("Grant not found.")
    if not oauth_service.revoke_grant(row, datetime.now(UTC)):
        return
    # `role_change` is the catch-all action for access changes; `event` separates this one.
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
