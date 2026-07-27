"""Audit API router (``/api/admin/audit``): read, verify, revert.

RBAC is fail-closed. A request without a session gets 401. A request without the
permission gets 403. The read view resolves actor subs, target ids and ``data``
UUIDs to display names on the server.

WARNING: ``audit.read`` is a GLOBAL platform-wide read permission with no Gremium
scope. The resolved log exposes PII across all Gremien. Grant it to the ``admin``
role only. There is no "scoped" auditing.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime

from app.deps import DbSession, Principal, require_principal
from app.modules.audit.schemas import (
    AuditActorOut,
    AuditEntryOut,
    AuditPageOut,
    AuditRevertOut,
    ChainVerificationOut,
)
from app.modules.audit.service import AuditService, data_uuid_strings
from app.modules.config_revision.revert import RevertService
from app.shared.errors import ProblemDetail
from app.shared.paging import DEFAULT_LIMIT, MAX_LIMIT

router = APIRouter(prefix="/admin/audit", tags=["audit"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}
_AUTH_ERRORS: dict[int | str, dict[str, Any]] = {401: _PROBLEM, 403: _PROBLEM}


def get_audit_service(session: DbSession) -> AuditService:
    return AuditService(session)


ServiceDep = Annotated[AuditService, Depends(get_audit_service)]


@router.get(
    "",
    response_model=AuditPageOut,
    dependencies=[Depends(require_principal("audit.read"))],
    responses=_AUTH_ERRORS,
)
async def list_audit(
    service: ServiceDep,
    action: Annotated[str | None, Query()] = None,
    actor: Annotated[str | None, Query()] = None,
    # AwareDatetime: the ``at`` column is timestamptz. asyncpg rejects a naive
    # value with a 500, so Pydantic rejects it up front with 422.
    since: Annotated[AwareDatetime | None, Query()] = None,
    until: Annotated[AwareDatetime | None, Query()] = None,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> AuditPageOut:
    """Read the audit log with keyset paging.

    The ``before`` cursor pages backwards and the newest entry comes first. Filter
    by ``action``, by ``actor``, or by the time window ``since``/``until``.
    """
    items, has_more = await service.query_cursor(
        action=action,
        actor=actor,
        since=since,
        until=until,
        before=before,
        limit=limit,
    )
    names = await service.resolve_actor_names([e.actor for e in items])
    labels = await service.resolve_target_labels(
        [(e.target_type, e.target_id) for e in items]
    )
    resolved_ids = await service.resolve_data_ids([e.data for e in items])
    revertable = await service.revertable_flags(items)
    out = [
        AuditEntryOut.from_entry(
            e,
            names.get(e.actor or ""),
            labels.get((e.target_type or "", e.target_id or "")),
            {
                k: resolved_ids[k]
                for k in data_uuid_strings(e.data)
                if k in resolved_ids
            },
            revertable=revertable.get(e.id, False),
        )
        for e in items
    ]
    return AuditPageOut(
        items=out,
        nextCursor=items[-1].id if (has_more and items) else None,
        hasMore=has_more,
    )


@router.get(
    "/actors",
    response_model=list[AuditActorOut],
    dependencies=[Depends(require_principal("audit.read"))],
    responses=_AUTH_ERRORS,
)
async def list_audit_actors(service: ServiceDep) -> list[AuditActorOut]:
    """List distinct log actors for the actor filter, with resolved names."""
    return [
        AuditActorOut(sub=sub, name=name) for sub, name in await service.list_actors()
    ]


@router.get(
    "/verify",
    response_model=ChainVerificationOut,
    # Chain verification has its own permission (audit.verify). Reads stay audit.read.
    dependencies=[Depends(require_principal("audit.verify"))],
    responses=_AUTH_ERRORS,
)
async def verify_audit_chain(service: ServiceDep) -> ChainVerificationOut:
    """Recompute the hash chain and report ``valid`` plus the first break, if any."""
    result = await service.verify_chain()
    return ChainVerificationOut(
        valid=result.valid,
        checked=result.checked,
        brokenAt=result.broken_at,
        reason=result.reason,
    )


@router.post(
    "/{entry_id}/revert",
    response_model=AuditRevertOut,
    # Destructive. It has its own permission, separate from audit.read and audit.verify.
    # 404 when the entry or the revision is missing. 409 when it is not revertable or stale.
    dependencies=[Depends(require_principal("audit.revert"))],
    responses={**_AUTH_ERRORS, 404: _PROBLEM, 409: _PROBLEM},
)
async def revert_audit_entry(
    entry_id: int,
    session: DbSession,
    principal: Annotated[Principal, Depends(require_principal("audit.revert"))],
) -> AuditRevertOut:
    """Revert the change that ``entry_id`` describes.

    The call restores the prior state. It answers 409 on a conflict. The platform
    logs the revert itself, and that log entry is revertable too.
    """
    # audit.revert gates the route. RevertService also re-asserts the granular
    # permission of the original operation. That is why the route passes the
    # principal through.
    result = await RevertService(session).revert(entry_id, principal.sub, principal)
    return AuditRevertOut(
        revertedAuditId=result.reverted_audit_id,
        entityType=result.entity_type,
        entityId=result.entity_id,
    )
