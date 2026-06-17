"""audit-API-Router (T-23, api.md ``/admin/audit``).

* ``GET /api/admin/audit``        — P(``audit.read``); gefiltertes, gepagtes Audit-Log.
* ``GET /api/admin/audit/verify`` — P(``audit.read``); Hash-Ketten-Integrität.

RBAC fail-closed: ohne Session 401, ohne ``audit.read`` 403 (``require_principal``).
Antworten enthalten keine PII (nur id-Referenzen + Hashes).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.deps import DbSession, require_principal
from app.modules.audit.schemas import (
    AuditActorOut,
    AuditEntryOut,
    AuditPageOut,
    ChainVerificationOut,
)
from app.modules.audit.service import AuditService, data_uuid_strings
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
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> AuditPageOut:
    """Audit-Log lesen — Keyset-Paging (``before``-Cursor, neueste zuerst).

    Filter: ``action``/``actor``/Zeitfenster (``since``/``until``). Akteur-``sub``
    wird auf den Klarnamen aufgelöst (``actorName``)."""
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
    out = [
        AuditEntryOut.from_entry(
            e,
            names.get(e.actor or ""),
            labels.get((e.target_type or "", e.target_id or "")),
            # nur die in diesem Eintrag tatsächlich vorkommenden Ids weiterreichen
            {
                k: resolved_ids[k]
                for k in data_uuid_strings(e.data)
                if k in resolved_ids
            },
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
    """Distinkte Akteure des Logs (für den Actor-Filter), Klarname aufgelöst."""
    return [
        AuditActorOut(sub=sub, name=name) for sub, name in await service.list_actors()
    ]


@router.get(
    "/verify",
    response_model=ChainVerificationOut,
    # #6: Ketten-Verifikation separat gegatet (audit.verify), Lesesicht bleibt audit.read.
    dependencies=[Depends(require_principal("audit.verify"))],
    responses=_AUTH_ERRORS,
)
async def verify_audit_chain(service: ServiceDep) -> ChainVerificationOut:
    """Hash-Kette nachrechnen → ``valid`` + ggf. erster Bruch (``brokenAt``/``reason``)."""
    result = await service.verify_chain()
    return ChainVerificationOut(
        valid=result.valid,
        checked=result.checked,
        brokenAt=result.broken_at,
        reason=result.reason,
    )
