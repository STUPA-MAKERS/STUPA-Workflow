"""audit-API-Router (T-23, api.md ``/admin/audit``).

* ``GET /api/admin/audit``        — P(``audit.read``); gefiltertes, gepagtes Audit-Log.
* ``GET /api/admin/audit/verify`` — P(``audit.read``); Hash-Ketten-Integrität.

RBAC fail-closed: ohne Session 401, ohne ``audit.read`` 403 (``require_principal``).
Die rohen ``audit_entry``-Zeilen enthalten nur id-Referenzen + Hashes — aber die
Lesesicht löst Akteur-``sub``, Ziel- und ``data``-UUIDs serverseitig auf Klarnamen,
E-Mails und Titel auf (``resolve_actor_names``/``resolve_target_labels``/
``resolve_data_ids``).

WARNUNG (#AUD-019, Least-Privilege-Hinweis): ``audit.read`` ist eine GLOBALE,
plattformweite Leseberechtigung OHNE Gremiums-Scoping. Das aufgelöste Log umfasst
PII (Mitglieder-E-Mails, alle Antragstitel, alle Abstimmungsfragen) GREMIUMS-
ÜBERGREIFEND. Die Berechtigung NICHT für „scoped"/gremiumsbeschränktes Auditing
vergeben — es gibt keine solche Eingrenzung; ein Inhaber von ``audit.read`` liest das
gesamte Plattform-Log. Standardmäßig nur der ``admin``-Rolle zuteilen.
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
    # tz-aware erzwingen (#AUD-034): die ``at``-Spalte ist ``timestamptz`` — ein
    # naiver Wert würde vom asyncpg-Codec abgelehnt (DataError → 500). ``AwareDatetime``
    # lässt Pydantic naive Eingaben schon bei der Validierung mit 422 zurückweisen.
    since: Annotated[AwareDatetime | None, Query()] = None,
    until: Annotated[AwareDatetime | None, Query()] = None,
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
    revertable = await service.revertable_flags(items)
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


@router.post(
    "/{entry_id}/revert",
    response_model=AuditRevertOut,
    # #config-versioning: Rücknahme eines Config-Changes — eigene, destruktive
    # Permission (getrennt von audit.read/verify). 404 Eintrag/Revision fehlt,
    # 409 nicht revertierbar / stale (neuerer Stand existiert).
    dependencies=[Depends(require_principal("audit.revert"))],
    responses={**_AUTH_ERRORS, 404: _PROBLEM, 409: _PROBLEM},
)
async def revert_audit_entry(
    entry_id: int,
    session: DbSession,
    principal: Annotated[Principal, Depends(require_principal("audit.revert"))],
) -> AuditRevertOut:
    """Den durch ``entry_id`` beschriebenen Config-Change zurücknehmen (Vorgänger-Stand
    wiederherstellen, bei Konflikt 409). Der Revert ist selbst geloggt + revertierbar."""
    # audit.revert ist die Router-Gatung; RevertService re-asserted zusätzlich die
    # granulare Permission des Original-Vorgangs (#AUD-018) → principal durchreichen.
    result = await RevertService(session).revert(entry_id, principal.sub, principal)
    return AuditRevertOut(
        revertedAuditId=result.reverted_audit_id,
        entityType=result.entity_type,
        entityId=result.entity_id,
    )
