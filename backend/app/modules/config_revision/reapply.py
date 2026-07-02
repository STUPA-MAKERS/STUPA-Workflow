"""Reapply a snapshot to the live config (restore/revert core).

A stored snapshot is replayed through the responsible config service via the
normal save path (new immutable version + linked ``config_revision`` + audit);
only the audit ``action``/``extra_data`` differ from an ordinary edit. Config
services are imported lazily to avoid import cycles.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.config_revision.service import (
    ENTITY_FLOW,
    ENTITY_FORM,
    ENTITY_SITE_CONFIG,
)
from app.shared.errors import ValidationProblem


async def reapply_snapshot(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: str,
    snapshot: dict[str, Any],
    actor: str,
    action: AuditAction,
    extra_data: dict[str, Any] | None = None,
) -> None:
    """Replay ``snapshot`` as the new active version of the entity.

    Writes a new version via the responsible config service plus the linked
    ``config_revision``/audit entry (action/extra as given).
    """
    if entity_type == ENTITY_FLOW:
        from app.modules.admin.schemas import FlowVersionCreate
        from app.modules.admin.service import ConfigService
        from app.shared.config_schemas import FlowGraph

        graph = FlowGraph.model_validate(snapshot)
        await ConfigService(session).create_global_flow_version(
            FlowVersionCreate(graph=graph), actor, action=action, extra_data=extra_data
        )
    elif entity_type == ENTITY_FORM:
        from app.modules.forms.schemas import FormVersionCreate
        from app.modules.forms.service import FormsService
        from app.shared.config_schemas import FormFieldDef

        fields = [
            FormFieldDef.model_validate(f) for f in snapshot.get("fields", []) or []
        ]
        payload = FormVersionCreate(
            fields=fields, activate=True, description=snapshot.get("description")
        )
        await FormsService(session).create_form_version(
            UUID(entity_id), payload, actor, action=action, extra_data=extra_data
        )
    elif entity_type == ENTITY_SITE_CONFIG:
        from app.modules.admin.branding import Branding
        from app.modules.admin.site_config_service import SiteConfigService

        branding = Branding.model_validate(snapshot)
        await SiteConfigService(session).restore_branding(
            branding, actor, action=action, extra_data=extra_data
        )
    else:  # pragma: no cover - defensive; entity_type comes from a closed list
        raise ValidationProblem(
            "Unsupported config entity for restore.",
            errors=[{"field": "entityType", "msg": entity_type}],
        )
