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
from app.modules.audit.schemas import AuditEntryOut, ChainVerificationOut
from app.modules.audit.service import AuditService
from app.shared.errors import ProblemDetail
from app.shared.paging import Page, PageParams

router = APIRouter(prefix="/admin/audit", tags=["audit"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}
_AUTH_ERRORS: dict[int | str, dict[str, Any]] = {401: _PROBLEM, 403: _PROBLEM}


def get_audit_service(session: DbSession) -> AuditService:
    return AuditService(session)


ServiceDep = Annotated[AuditService, Depends(get_audit_service)]


@router.get(
    "",
    response_model=Page[AuditEntryOut],
    dependencies=[Depends(require_principal("audit.read"))],
    responses=_AUTH_ERRORS,
)
async def list_audit(
    service: ServiceDep,
    page: Annotated[PageParams, Depends()],
    action: Annotated[str | None, Query()] = None,
    actor: Annotated[str | None, Query()] = None,
    target_type: Annotated[str | None, Query(alias="targetType")] = None,
    target_id: Annotated[str | None, Query(alias="targetId")] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
) -> Page[AuditEntryOut]:
    """Audit-Log lesen (Filter: action/actor/target/Zeitfenster; Offset-Paging)."""
    result = await service.query(
        action=action,
        actor=actor,
        target_type=target_type,
        target_id=target_id,
        since=since,
        until=until,
        limit=page.limit,
        offset=page.offset,
    )
    return Page(
        items=[AuditEntryOut.from_entry(e) for e in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.get(
    "/verify",
    response_model=ChainVerificationOut,
    dependencies=[Depends(require_principal("audit.read"))],
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
