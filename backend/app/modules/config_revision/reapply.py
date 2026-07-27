"""Reapply a snapshot to the live config: the core of restore and revert.

This module replays a stored snapshot through the responsible config service on the
normal save path. That path writes a new immutable version, the linked
``config_revision`` and the audit entry. Only the audit ``action`` and ``extra_data``
differ from an ordinary edit. The module imports the config services lazily to avoid
import cycles.
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

    The responsible config service writes a new version. It also writes the linked
    ``config_revision`` and the audit entry with the given ``action`` and
    ``extra_data``. ``entity_type`` is one of ``form``, ``flow`` or ``site_config``.
    ``entity_id`` holds the application type id for a form, or ``global`` for the flow
    and the site config. ``actor`` is the OIDC ``sub`` to record.

    Raises:
        ValidationProblem: ``entity_type`` is not a known config entity.
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
