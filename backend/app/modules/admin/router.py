"""Admin-/Config-API-Router (T-24, api.md »admin«).

Endpunkte für versionierte Config-CRUD (gremien, application-types, **flow-versions**),
RBAC (roles/role-assignments/group-mappings), webhooks, ``config-schemas`` und
**site-config/Branding** (#21) + ein öffentlicher, auth-freier Branding-Read.

RBAC ist serverseitig **autoritativ** (``require_principal`` → 401/403); das FE ist
nur UX-Gate. Permissions je Bereich:
``admin.config`` (Config), ``admin.roles`` (RBAC), ``webhook.manage`` (Webhooks).
Fehler werden als ``ProblemDetail`` deklariert (T-10-Hook → problem+json),
``400`` = malformed JSON body, ``422`` = Schema-Validierung.

``notification-rules``/``mail-templates`` (api.md) liegen im notifications-Modul
(T-18), ``/admin/audit`` im audit-Modul (T-23); ``/admin/application-types/{id}/
form-versions`` im forms-Modul (T-11) — hier nicht dupliziert.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.deps import DbSession, Principal, require_principal
from app.modules.admin.branding import Branding
from app.modules.admin.schemas import (
    ApplicationTypeCreate,
    ApplicationTypeOut,
    ApplicationTypeUpdate,
    FlowVersionCreate,
    FlowVersionOut,
    GremiumCreate,
    GremiumOut,
    GremiumUpdate,
    GroupMappingCreate,
    GroupMappingOut,
    GroupMappingUpdate,
    PrincipalOut,
    PrincipalUpdate,
    PublicSiteConfigOut,
    RoleAssignmentCreate,
    RoleAssignmentOut,
    RoleAssignmentUpdate,
    RoleCreate,
    RoleOut,
    RoleUpdate,
    SiteConfigOut,
    WebhookCreate,
    WebhookOut,
    WebhookUpdate,
)
from app.modules.admin.service import ConfigService
from app.modules.admin.site_config_service import SiteConfigService
from app.shared.config_schemas import export_json_schemas
from app.shared.errors import ProblemDetail

router = APIRouter(prefix="/admin", tags=["admin"])
public_router = APIRouter(tags=["admin"])
# Authentifiziert (irgendein Principal), aber **ohne** Admin-Recht: Stammdaten-
# Reads, die mehrere Rollen als Dropdown-Quelle brauchen (#68 Sitzung anlegen,
# Budget-Topf, Antragstyp). Eigener Router, da ohne `/admin`-Prefix gemountet.
authed_router = APIRouter(tags=["gremien"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_config_service(session: DbSession) -> ConfigService:
    return ConfigService(session)


def get_site_config_service(session: DbSession) -> SiteConfigService:
    return SiteConfigService(session)


ServiceDep = Annotated[ConfigService, Depends(get_config_service)]
SiteServiceDep = Annotated[SiteConfigService, Depends(get_site_config_service)]

# Permission-Gates (Principal-Objekt injiziert für den Audit-actor).
ConfigAdmin = Annotated[Principal, Depends(require_principal("admin.config"))]
RolesAdmin = Annotated[Principal, Depends(require_principal("admin.roles"))]
WebhookAdmin = Annotated[Principal, Depends(require_principal("webhook.manage"))]

_CONFIG = Depends(require_principal("admin.config"))
_ROLES = Depends(require_principal("admin.roles"))
_WEBHOOK = Depends(require_principal("webhook.manage"))


# =========================================================================== #
# config-schemas (JSON-Schema-Export für die FE-Editoren)
# =========================================================================== #
@router.get(
    "/config-schemas",
    response_model=dict[str, dict[str, Any]],
    dependencies=[_CONFIG],
    responses=_errors(401, 403),
)
async def get_config_schemas() -> dict[str, dict[str, Any]]:
    """JSON-Schemas (Form/Flow/Voting/Branding/…) für die Config-Editoren."""
    return export_json_schemas()


# =========================================================================== #
# Gremien
# =========================================================================== #
@router.get(
    "/gremien",
    response_model=list[GremiumOut],
    dependencies=[_CONFIG],
    responses=_errors(401, 403),
)
async def list_gremien(service: ServiceDep) -> list[GremiumOut]:
    return await service.list_gremien()


@router.post(
    "/gremien",
    response_model=GremiumOut,
    status_code=201,
    responses=_errors(400, 401, 403, 409, 422),
)
async def create_gremium(
    payload: GremiumCreate, service: ServiceDep, principal: ConfigAdmin
) -> GremiumOut:
    return await service.create_gremium(payload, principal.sub)


@router.patch(
    "/gremien/{gremium_id}",
    response_model=GremiumOut,
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def update_gremium(
    gremium_id: UUID,
    payload: GremiumUpdate,
    service: ServiceDep,
    principal: ConfigAdmin,
) -> GremiumOut:
    return await service.update_gremium(gremium_id, payload, principal.sub)


@router.delete(
    "/gremien/{gremium_id}",
    status_code=204,
    responses=_errors(401, 403, 404),
)
async def delete_gremium(
    gremium_id: UUID, service: ServiceDep, principal: ConfigAdmin
) -> None:
    await service.delete_gremium(gremium_id, principal.sub)


# =========================================================================== #
# Gremien (authentifiziert, ohne Admin-Recht) — Dropdown-Quelle (#68)
# =========================================================================== #
@authed_router.get(
    "/gremien",
    response_model=list[GremiumOut],
    responses=_errors(401),
)
async def list_gremien_authed(
    service: ServiceDep,
    _principal: Annotated[Principal, Depends(require_principal())],
) -> list[GremiumOut]:
    """Gremien als Stammdaten für jeden eingeloggten Principal (#68): Quelle der
    Gremium-Auswahl in »Sitzung anlegen«, Budget-Topf und Antragstyp. Reine
    Lese-Stammdaten (id/Name/Variante) — Anlegen/Ändern bleibt ``admin.config``."""
    return await service.list_gremien()


# =========================================================================== #
# Application-Types
# =========================================================================== #
@router.get(
    "/application-types",
    response_model=list[ApplicationTypeOut],
    dependencies=[_CONFIG],
    responses=_errors(401, 403),
)
async def list_application_types(service: ServiceDep) -> list[ApplicationTypeOut]:
    return await service.list_application_types()


@router.post(
    "/application-types",
    response_model=ApplicationTypeOut,
    status_code=201,
    responses=_errors(400, 401, 403, 409, 422),
)
async def create_application_type(
    payload: ApplicationTypeCreate, service: ServiceDep, principal: ConfigAdmin
) -> ApplicationTypeOut:
    return await service.create_application_type(payload, principal.sub)


@router.patch(
    "/application-types/{type_id}",
    response_model=ApplicationTypeOut,
    responses=_errors(400, 401, 403, 404, 422),
)
async def update_application_type(
    type_id: UUID,
    payload: ApplicationTypeUpdate,
    service: ServiceDep,
    principal: ConfigAdmin,
) -> ApplicationTypeOut:
    return await service.update_application_type(type_id, payload, principal.sub)


# =========================================================================== #
# Flow-Versionen (Graph validiert; mirror der Form-Versionen aus T-11)
# =========================================================================== #
@router.post(
    "/application-types/{type_id}/flow-versions",
    response_model=FlowVersionOut,
    status_code=201,
    responses=_errors(400, 401, 403, 404, 422),
)
async def create_flow_version(
    type_id: UUID,
    payload: FlowVersionCreate,
    service: ServiceDep,
    principal: ConfigAdmin,
) -> FlowVersionOut:
    """Neue Flow-Version anlegen (Graph wird serverseitig validiert)."""
    return await service.create_flow_version(type_id, payload, principal.sub)


# =========================================================================== #
# Rollen / RBAC + Vertretung
# =========================================================================== #
@router.get(
    "/principals",
    response_model=list[PrincipalOut],
    dependencies=[_ROLES],
    responses=_errors(401, 403),
)
async def list_principals(
    service: ServiceDep, q: Annotated[str | None, Query()] = None
) -> list[PrincipalOut]:
    """Benutzer (OIDC-Principals) auflisten/suchen (per `sub`/Name/E-Mail) — #72."""
    return await service.search_principals(q)


@router.patch(
    "/principals/{principal_id}",
    response_model=PrincipalOut,
    responses=_errors(401, 403, 404, 422),
)
async def patch_principal(
    principal_id: UUID, payload: PrincipalUpdate, service: ServiceDep, principal: RolesAdmin
) -> PrincipalOut:
    """Benutzer aktivieren/deaktivieren (#30)."""
    return await service.set_principal_active(principal_id, payload.active, principal.sub)


@router.get(
    "/permissions",
    response_model=list[str],
    dependencies=[_ROLES],
    responses=_errors(401, 403),
)
async def list_permissions(service: ServiceDep) -> list[str]:
    """Katalog wählbarer Permission-Keys fürs Rollen-/Rechte-UI (api.md §1)."""
    return service.list_permissions()


@router.get(
    "/roles",
    response_model=list[RoleOut],
    dependencies=[_CONFIG],
    responses=_errors(401, 403),
)
async def list_roles(service: ServiceDep) -> list[RoleOut]:
    return await service.list_roles()


@router.post(
    "/roles",
    response_model=RoleOut,
    status_code=201,
    responses=_errors(400, 401, 403, 409, 422),
)
async def create_role(
    payload: RoleCreate, service: ServiceDep, principal: RolesAdmin
) -> RoleOut:
    return await service.create_role(payload, principal.sub)


@router.patch(
    "/roles/{role_id}",
    response_model=RoleOut,
    responses=_errors(400, 401, 403, 404, 422),
)
async def update_role(
    role_id: UUID, payload: RoleUpdate, service: ServiceDep, principal: RolesAdmin
) -> RoleOut:
    return await service.update_role(role_id, payload, principal.sub)


@router.delete(
    "/roles/{role_id}",
    status_code=204,
    responses=_errors(401, 403, 404, 409),
)
async def delete_role(
    role_id: UUID, service: ServiceDep, principal: RolesAdmin
) -> None:
    """Rolle löschen (#38); ``admin``/``member`` sind geschützt (409)."""
    await service.delete_role(role_id, principal.sub)


@router.get(
    "/role-assignments",
    response_model=list[RoleAssignmentOut],
    dependencies=[_ROLES],
    responses=_errors(401, 403),
)
async def list_role_assignments(service: ServiceDep) -> list[RoleAssignmentOut]:
    return await service.list_role_assignments()


@router.post(
    "/role-assignments",
    response_model=RoleAssignmentOut,
    status_code=201,
    responses=_errors(400, 401, 403, 404, 422),
)
async def create_role_assignment(
    payload: RoleAssignmentCreate, service: ServiceDep, principal: RolesAdmin
) -> RoleAssignmentOut:
    return await service.create_role_assignment(payload, principal.sub)


@router.patch(
    "/role-assignments/{assignment_id}",
    response_model=RoleAssignmentOut,
    responses=_errors(400, 401, 403, 404, 422),
)
async def update_role_assignment(
    assignment_id: UUID,
    payload: RoleAssignmentUpdate,
    service: ServiceDep,
    principal: RolesAdmin,
) -> RoleAssignmentOut:
    return await service.update_role_assignment(assignment_id, payload, principal.sub)


@router.delete(
    "/role-assignments/{assignment_id}",
    status_code=204,
    responses=_errors(401, 403, 404),
)
async def delete_role_assignment(
    assignment_id: UUID, service: ServiceDep, principal: RolesAdmin
) -> Response:
    """Rolle entziehen (#72): Zuweisung löschen (idempotent → 204; unbekannt → 404)."""
    await service.delete_role_assignment(assignment_id, principal.sub)
    return Response(status_code=204)


@router.get(
    "/group-mappings",
    response_model=list[GroupMappingOut],
    dependencies=[_ROLES],
    responses=_errors(401, 403),
)
async def list_group_mappings(service: ServiceDep) -> list[GroupMappingOut]:
    return await service.list_group_mappings()


@router.post(
    "/group-mappings",
    response_model=GroupMappingOut,
    status_code=201,
    responses=_errors(400, 401, 403, 404, 422),
)
async def create_group_mapping(
    payload: GroupMappingCreate, service: ServiceDep, principal: RolesAdmin
) -> GroupMappingOut:
    return await service.create_group_mapping(payload, principal.sub)


@router.patch(
    "/group-mappings/{mapping_id}",
    response_model=GroupMappingOut,
    responses=_errors(400, 401, 403, 404, 422),
)
async def update_group_mapping(
    mapping_id: UUID,
    payload: GroupMappingUpdate,
    service: ServiceDep,
    principal: RolesAdmin,
) -> GroupMappingOut:
    return await service.update_group_mapping(mapping_id, payload, principal.sub)


# =========================================================================== #
# Webhooks (P webhook.manage)
# =========================================================================== #
@router.get(
    "/webhooks",
    response_model=list[WebhookOut],
    dependencies=[_WEBHOOK],
    responses=_errors(401, 403),
)
async def list_webhooks(service: ServiceDep) -> list[WebhookOut]:
    return await service.list_webhooks()


@router.post(
    "/webhooks",
    response_model=WebhookOut,
    status_code=201,
    responses=_errors(400, 401, 403, 422),
)
async def create_webhook(
    payload: WebhookCreate, service: ServiceDep, principal: WebhookAdmin
) -> WebhookOut:
    return await service.create_webhook(payload, principal.sub)


@router.patch(
    "/webhooks/{webhook_id}",
    response_model=WebhookOut,
    responses=_errors(400, 401, 403, 404, 422),
)
async def update_webhook(
    webhook_id: UUID,
    payload: WebhookUpdate,
    service: ServiceDep,
    principal: WebhookAdmin,
) -> WebhookOut:
    return await service.update_webhook(webhook_id, payload, principal.sub)


# =========================================================================== #
# Site-Config / Branding (#21) — Draft/Activate (FE-Kontrakt T-34)
# =========================================================================== #
@router.get(
    "/site-config",
    response_model=SiteConfigOut,
    dependencies=[_CONFIG],
    responses=_errors(401, 403),
)
async def get_site_config(service: SiteServiceDep) -> SiteConfigOut:
    """Aktive Branding-Config + aktueller Draft + Änderungsflag."""
    return await service.get()


@router.put(
    "/site-config/draft",
    response_model=SiteConfigOut,
    responses=_errors(400, 401, 403, 422),
)
async def put_site_config_draft(
    payload: Branding, service: SiteServiceDep, principal: ConfigAdmin
) -> SiteConfigOut:
    """Branding-Draft setzen (Bild-only-Logos, kein Inline-SVG; ungültig → 422)."""
    return await service.put_draft(payload, principal.sub)


@router.post(
    "/site-config/activate",
    response_model=SiteConfigOut,
    responses=_errors(400, 401, 403, 409),
)
async def activate_site_config(
    service: SiteServiceDep, principal: ConfigAdmin
) -> SiteConfigOut:
    """Draft aktivieren → neue aktive Version (Versionssprung, auditiert)."""
    return await service.activate(principal.sub)


# =========================================================================== #
# Öffentliche Branding-Config (auth-frei, fürs FE-Rendering, #21)
# =========================================================================== #
@public_router.get("/site-config", response_model=PublicSiteConfigOut)
async def get_public_site_config(
    service: SiteServiceDep, response: Response
) -> PublicSiteConfigOut:
    """Aktive Branding-Config ohne Auth (Logos-URLs, Footer, Texte)."""
    response.headers["Cache-Control"] = "public, max-age=300"
    return await service.public()
