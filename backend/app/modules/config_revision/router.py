"""config_revision-API-Router (#config-versioning).

* ``GET  /admin/config-revisions``            — Versions-Sidebar-Feed je Entität.
* ``GET  /admin/config-revisions/{id}/diff``  — Feld-Diff gegen den Vorgänger.
* ``POST /admin/config-revisions/{id}/restore`` — einen früheren Stand als neue
  aktive Version zurückspielen (Vorwärts-Restore; pro Entität gegatet).

Lesen ist für Audit- **oder** Config-Editoren freigegeben; der Restore verlangt die
jeweilige Config-Permission (form.configure / flow.configure / admin.site).
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.deps import DbSession, Principal, require_any_permission, require_principal
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import AuditService
from app.modules.config_revision.models import ConfigRevision
from app.modules.config_revision.reapply import reapply_snapshot
from app.modules.config_revision.schemas import (
    ConfigRevisionDiffOut,
    ConfigRevisionOut,
)
from app.modules.config_revision.service import (
    ENTITY_FLOW,
    ENTITY_FORM,
    ENTITY_SITE_CONFIG,
    ConfigRevisionService,
)
from app.shared.errors import ForbiddenError, NotFoundError, ProblemDetail

router = APIRouter(prefix="/admin/config-revisions", tags=["config-revision"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}
_AUTH_ERRORS: dict[int | str, dict[str, Any]] = {401: _PROBLEM, 403: _PROBLEM}

# Lesen: Audit-Leser ODER ein Config-Editor (Sidebar lebt in den Editoren).
_READABLE = Depends(
    require_any_permission(
        "audit.read", "form.configure", "flow.configure", "admin.site"
    )
)

# Restore-Gate je Entität.
_RESTORE_PERM: dict[str, str] = {
    ENTITY_FORM: "form.configure",
    ENTITY_FLOW: "flow.configure",
    ENTITY_SITE_CONFIG: "admin.site",
}


def get_service(session: DbSession) -> ConfigRevisionService:
    return ConfigRevisionService(session)


ServiceDep = Annotated[ConfigRevisionService, Depends(get_service)]


def _require_restore_perm(principal: Principal, entity_type: str) -> None:
    perm = _RESTORE_PERM.get(entity_type)
    if perm is None or not principal.has(perm):
        raise ForbiddenError(
            f"Missing permission to restore {entity_type} config."
        )


@router.get(
    "",
    response_model=list[ConfigRevisionOut],
    dependencies=[_READABLE],
    responses=_AUTH_ERRORS,
)
async def list_config_revisions(
    service: ServiceDep,
    entity_type: Annotated[str, Query(alias="entityType")],
    entity_id: Annotated[str, Query(alias="entityId")],
) -> list[ConfigRevisionOut]:
    """Snapshots einer Entität (neueste zuerst) — Versions-Sidebar."""
    rows = await service.list_for(entity_type, entity_id)
    names = await AuditService(service.session).resolve_actor_names(
        [r.created_by for r in rows]
    )
    head_id = rows[0].id if rows else None
    return [
        ConfigRevisionOut.from_row(
            r,
            created_by_name=names.get(r.created_by or ""),
            is_current=(r.id == head_id),
        )
        for r in rows
    ]


@router.get(
    "/{revision_id}/diff",
    response_model=ConfigRevisionDiffOut,
    dependencies=[_READABLE],
    responses={**_AUTH_ERRORS, 404: _PROBLEM},
)
async def get_config_revision_diff(
    revision_id: UUID,
    service: ServiceDep,
) -> ConfigRevisionDiffOut:
    """Feld-Diff eines Snapshots gegen seinen Vorgänger (#2-Diff)."""
    revision = await service.get(revision_id)
    if revision is None:
        raise NotFoundError(f"config revision {revision_id} not found")
    prev_version: int | None = None
    if revision.prev_revision_id is not None:
        prev = await service.get(revision.prev_revision_id)
        prev_version = prev.version if prev is not None else None
    diff = await service.diff(revision)
    return ConfigRevisionDiffOut(
        id=revision.id,
        entityType=revision.entity_type,
        entityId=revision.entity_id,
        version=revision.version,
        prevVersion=prev_version,
        diff=diff,
    )


@router.post(
    "/{revision_id}/restore",
    status_code=204,
    responses={**_AUTH_ERRORS, 404: _PROBLEM},
)
async def restore_config_revision(
    revision_id: UUID,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal())],
) -> None:
    """Einen früheren Snapshot als **neue aktive Version** zurückspielen (Sidebar-Restore).

    Vorwärts-Operation (kein Konflikt-Block): macht den gewählten Stand wieder aktuell;
    frühere Versionen bleiben erhalten. Pro Entität gegatet (form/flow/site_config)."""
    revision: ConfigRevision | None = await service.get(revision_id)
    if revision is None:
        raise NotFoundError(f"config revision {revision_id} not found")
    _require_restore_perm(principal, revision.entity_type)
    await reapply_snapshot(
        service.session,
        entity_type=revision.entity_type,
        entity_id=revision.entity_id,
        snapshot=revision.snapshot or {},
        actor=principal.sub,
        action=AuditAction.CONFIG_CHANGE,
        extra_data={"restoredFromVersion": revision.version},
    )
