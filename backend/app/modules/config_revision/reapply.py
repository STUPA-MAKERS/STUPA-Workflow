"""Snapshot → Live-Config wieder anwenden (Restore/Revert-Kern, #config-versioning).

Ein gespeicherter ``config_revision``-Snapshot wird in seiner natürlichen Form in den
zuständigen Config-Service zurückgespielt. Das geht über den **normalen Speicher-Pfad**
(neue, unveränderliche Version + verlinkter ``config_revision`` + Audit) — der einzige
Unterschied zu einem gewöhnlichen Edit ist die ``action``/``extra_data`` des Audit-
Eintrags (``config_change`` bei Sidebar-Restore, ``config_revert`` aus dem Audit-Log).

Lazy-Importe der Config-Services vermeiden Import-Zyklen (admin/forms importieren das
config_revision-Modul nicht zur Modulzeit).
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
    """``snapshot`` als neue aktive Version der Entität zurückspielen.

    Schreibt über den jeweiligen Config-Service eine neue Version **und** den
    verlinkten ``config_revision``/Audit-Eintrag (Action/Extra wie übergeben).
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
    else:  # pragma: no cover - defensiv; entity_type stammt aus geschlossener Liste
        raise ValidationProblem(
            "Unsupported config entity for restore.",
            errors=[{"field": "entityType", "msg": entity_type}],
        )
