"""Admin-/Config-API-Router (T-24, api.md »admin«).

Endpunkte für versionierte Config-CRUD (gremien, application-types, **flow-versions**),
RBAC (roles/role-assignments/group-mappings), webhooks, ``config-schemas`` und
**site-config/Branding** (#21) + ein öffentlicher, auth-freier Branding-Read.

RBAC ist serverseitig **autoritativ** (``require_principal`` → 401/403); das FE ist
nur UX-Gate. Permissions je Bereich (#6-Granularität):
``admin.gremien`` (Gremien), ``admin.types`` (Antragstypen/Forms/Flows),
``admin.site`` (Branding/Site-Config), ``admin.roles`` (RBAC),
``webhook.manage`` (Webhooks).
Fehler werden als ``ProblemDetail`` deklariert (T-10-Hook → problem+json),
``400`` = malformed JSON body, ``422`` = Schema-Validierung.

``notification-rules``/``mail-templates`` (api.md) liegen im notifications-Modul
(T-18), ``/admin/audit`` im audit-Modul (T-23); ``/admin/application-types/{id}/
form-versions`` im forms-Modul (T-11) — hier nicht dupliziert.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response

from app.deps import (
    DbSession,
    Principal,
    SettingsDep,
    require_any_permission,
    require_principal,
)
from app.modules.admin.branding import Branding
from app.modules.admin.gremium_roles import GremiumRoleService
from app.modules.admin.schemas import (
    ApplicationTypeCreate,
    ApplicationTypeOut,
    ApplicationTypeUpdate,
    FlowVersionCreate,
    FlowVersionOut,
    GremiumCreate,
    GremiumMailRecipients,
    GremiumMembershipCreate,
    GremiumMembershipOut,
    GremiumOut,
    GremiumRoleCreate,
    GremiumRoleOut,
    GremiumRoleUpdate,
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
    WebhookDeliveryStatusOut,
    WebhookOut,
    WebhookUpdate,
)
from app.modules.admin.service import ConfigService
from app.modules.admin.site_config_service import SiteConfigService
from app.modules.notifications.auto import (
    AutoMailer,
    assignment_mail_info,
    get_auto_mailer,
)
from app.shared.config_schemas import FlowGraph, export_json_schemas
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


def get_gremium_role_service(session: DbSession) -> GremiumRoleService:
    return GremiumRoleService(session)


ServiceDep = Annotated[ConfigService, Depends(get_config_service)]
SiteServiceDep = Annotated[SiteConfigService, Depends(get_site_config_service)]
GremiumRoleServiceDep = Annotated[GremiumRoleService, Depends(get_gremium_role_service)]

AutoMailerDep = Annotated[AutoMailer, Depends(get_auto_mailer)]

# Permission-Gates (Principal-Objekt injiziert für den Audit-actor). #6:
# ``admin.config`` ist in drei Bereichs-Rechte aufgeteilt (Migration 0017).
GremienAdmin = Annotated[Principal, Depends(require_principal("admin.gremien"))]
TypesAdmin = Annotated[Principal, Depends(require_principal("admin.types"))]
# Löschen von Antragsarten ist destruktiv → eigene Permission, getrennt von admin.types.
TypesDeleteAdmin = Annotated[Principal, Depends(require_principal("admin.types_delete"))]
SiteAdmin = Annotated[Principal, Depends(require_principal("admin.site"))]
RolesAdmin = Annotated[Principal, Depends(require_principal("admin.roles"))]
WebhookAdmin = Annotated[Principal, Depends(require_principal("webhook.manage"))]
# #per-page-admin: die zuvor von ``admin.roles`` mitgegatete Personen-/Zugriffs-
# verwaltung ist je Admin-Seite getrennt. ``admin.roles`` = /admin/roles (Rollen-
# Definition); die Schreib-Operationen der übrigen Seiten gaten auf eigene Keys.
UsersAdmin = Annotated[Principal, Depends(require_principal("admin.users"))]
GroupMappingsAdmin = Annotated[Principal, Depends(require_principal("admin.group_mappings"))]
GremiumRolesAdmin = Annotated[Principal, Depends(require_principal("admin.gremium_roles"))]

# Alle Admin-Bereichs-Rechte (für ANY-of-Reads + Admin-Landing).
_ALL_ADMIN_AREAS = (
    "admin.site",
    "admin.gremien",
    "admin.types",
    "admin.roles",
    "admin.users",
    "admin.group_mappings",
    "admin.gremium_roles",
    "admin.delegations",
    "admin.deadlines",
)

_GREMIEN = Depends(require_principal("admin.gremien"))
_TYPES = Depends(require_principal("admin.types"))
_SITE = Depends(require_principal("admin.site"))
_ROLES = Depends(require_principal("admin.roles"))
_USERS = Depends(require_principal("admin.users"))
_GROUP_MAPPINGS = Depends(require_principal("admin.group_mappings"))
_WEBHOOK = Depends(require_principal("webhook.manage"))
# Geteilte Reads, die mehrere Admin-Bereiche bedienen (ANY-of).
_ANY_ADMIN_AREA = Depends(require_any_permission(*_ALL_ADMIN_AREAS))
# Gremium-Mitglieder-Subseite (admin.gremien) braucht lesenden Zugriff auf
# Gremium-Rollen (Rollen-Dropdown) bzw. Principals (Namen + Typeahead), ohne dass
# der Gremien-Admin die jeweilige Schreib-Permission besitzen muss (#5-3).
_GREMIEN_OR_GREMIUM_ROLES = Depends(require_any_permission("admin.gremien", "admin.gremium_roles"))
_GREMIEN_OR_USERS = Depends(require_any_permission("admin.gremien", "admin.users"))
# Lese-Gates für Seiten, die fremde Bereichsdaten nur als Auswahl-/Anzeigequelle
# brauchen (#5-2). Schreiben bleibt jeweils auf dem strengen Recht.
#   * Flow-Editor (flow.configure) liest globalen Flow, Rollen, Webhooks, Fristen.
#   * Budget-Baum (budget.structure) liest den globalen Flow (Status-Dropdowns).
#   * Form-Editor (form.configure) liest Antragstypen.
_FLOW_READABLE = Depends(
    require_any_permission("admin.types", "flow.configure", "budget.structure")
)
# Rollen-Liste: gebraucht von der Rollen-Seite, der Benutzer-Seite (Zuweisungs-
# Dropdown) und diversen Konfig-Editoren als Anzeigequelle.
_ROLES_READ = Depends(
    require_any_permission(
        "admin.site",
        "admin.gremien",
        "admin.types",
        "admin.roles",
        "admin.users",
        "flow.configure",
    )
)
_WEBHOOK_OR_FLOW = Depends(require_any_permission("webhook.manage", "flow.configure"))
_TYPES_OR_FORM = Depends(require_any_permission("admin.types", "form.configure"))


# =========================================================================== #
# config-schemas (JSON-Schema-Export für die FE-Editoren)
# =========================================================================== #
@router.get(
    "/config-schemas",
    response_model=dict[str, dict[str, Any]],
    dependencies=[_ANY_ADMIN_AREA],
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
    dependencies=[_GREMIEN],
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
    payload: GremiumCreate, service: ServiceDep, principal: GremienAdmin
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
    principal: GremienAdmin,
) -> GremiumOut:
    return await service.update_gremium(gremium_id, payload, principal.sub)


@router.delete(
    "/gremien/{gremium_id}",
    status_code=204,
    responses=_errors(401, 403, 404),
)
async def delete_gremium(gremium_id: UUID, service: ServiceDep, principal: GremienAdmin) -> None:
    await service.delete_gremium(gremium_id, principal.sub)


@router.get(
    "/gremien/{gremium_id}/mail-recipients",
    response_model=GremiumMailRecipients,
    responses=_errors(401, 403, 404),
)
async def get_gremium_mail_recipients(
    gremium_id: UUID, service: ServiceDep, _principal: GremienAdmin
) -> GremiumMailRecipients:
    """Zusätzliche Protokoll-Empfänger des Gremiums (#protocol-recipients)."""
    return await service.get_gremium_mail_recipients(gremium_id)


@router.put(
    "/gremien/{gremium_id}/mail-recipients",
    response_model=GremiumMailRecipients,
    responses=_errors(400, 401, 403, 404, 422),
)
async def set_gremium_mail_recipients(
    gremium_id: UUID,
    payload: GremiumMailRecipients,
    service: ServiceDep,
    principal: GremienAdmin,
) -> GremiumMailRecipients:
    """Zusätzliche Protokoll-Empfänger ersetzen (idempotentes PUT). Diese Adressen
    erhalten finalisierte Protokolle zusätzlich zu den aktiven Gremium-Mitgliedern."""
    return await service.set_gremium_mail_recipients(gremium_id, payload, principal.sub)


# =========================================================================== #
# Gremium-Rollen (#42) — eigener Rollensatz + zeitbegrenzte Mitgliedschaften
# =========================================================================== #
@router.get(
    "/gremien/{gremium_id}/roles",
    response_model=list[GremiumRoleOut],
    dependencies=[_GREMIEN_OR_GREMIUM_ROLES],
    responses=_errors(401, 403),
)
async def list_gremium_roles(
    gremium_id: UUID, service: GremiumRoleServiceDep
) -> list[GremiumRoleOut]:
    return await service.list_roles(gremium_id)


@router.post(
    "/gremien/{gremium_id}/roles",
    response_model=GremiumRoleOut,
    status_code=201,
    responses=_errors(400, 401, 403, 409, 422),
)
async def create_gremium_role(
    gremium_id: UUID,
    payload: GremiumRoleCreate,
    service: GremiumRoleServiceDep,
    principal: GremiumRolesAdmin,
) -> GremiumRoleOut:
    return await service.create_role(gremium_id, payload, principal.sub)


@router.patch(
    "/gremium-roles/{role_id}",
    response_model=GremiumRoleOut,
    responses=_errors(400, 401, 403, 404, 422),
)
async def update_gremium_role(
    role_id: UUID,
    payload: GremiumRoleUpdate,
    service: GremiumRoleServiceDep,
    principal: GremiumRolesAdmin,
) -> GremiumRoleOut:
    return await service.update_role(role_id, payload, principal.sub)


@router.delete("/gremium-roles/{role_id}", status_code=204, responses=_errors(401, 403, 404, 409))
async def delete_gremium_role(
    role_id: UUID, service: GremiumRoleServiceDep, principal: GremiumRolesAdmin
) -> None:
    await service.delete_role(role_id, principal.sub)


@router.get(
    "/gremien/{gremium_id}/memberships",
    response_model=list[GremiumMembershipOut],
    dependencies=[_GREMIEN],
    responses=_errors(401, 403),
)
async def list_gremium_memberships(
    gremium_id: UUID, service: GremiumRoleServiceDep
) -> list[GremiumMembershipOut]:
    return await service.list_memberships(gremium_id)


@router.post(
    "/gremien/{gremium_id}/memberships",
    response_model=GremiumMembershipOut,
    status_code=201,
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def create_gremium_membership(
    gremium_id: UUID,
    payload: GremiumMembershipCreate,
    service: GremiumRoleServiceDep,
    principal: GremienAdmin,
) -> GremiumMembershipOut:
    return await service.create_membership(gremium_id, payload, principal.sub)


@router.delete(
    "/gremium-memberships/{membership_id}", status_code=204, responses=_errors(401, 403, 404)
)
async def delete_gremium_membership(
    membership_id: UUID, service: GremiumRoleServiceDep, principal: GremienAdmin
) -> None:
    await service.delete_membership(membership_id, principal.sub)


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
    Lese-Stammdaten (id/Name/Variante) — Anlegen/Ändern bleibt ``admin.gremien``."""
    return await service.list_gremien()


# =========================================================================== #
# Application-Types
# =========================================================================== #
@router.get(
    "/application-types",
    response_model=list[ApplicationTypeOut],
    dependencies=[_TYPES_OR_FORM],
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
    payload: ApplicationTypeCreate, service: ServiceDep, principal: TypesAdmin
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
    principal: TypesAdmin,
) -> ApplicationTypeOut:
    return await service.update_application_type(type_id, payload, principal.sub)


@router.delete(
    "/application-types/{type_id}",
    status_code=204,
    responses=_errors(401, 403, 404, 409),
)
async def delete_application_type(
    type_id: UUID, service: ServiceDep, principal: TypesDeleteAdmin
) -> None:
    """Antragsart löschen — eigene Permission ``admin.types_delete``. 409, wenn noch
    Anträge dieser Art existieren (die hängen an Formular-/Flow-Versionen)."""
    await service.delete_application_type(type_id, principal.sub)


# =========================================================================== #
# Globaler Flow (#28: es gibt genau EINEN Flow für alle Antragstypen)
# =========================================================================== #
@router.get(
    "/flow-versions/global",
    response_model=FlowGraph | None,
    dependencies=[_FLOW_READABLE],
    responses=_errors(401, 403),
)
async def get_global_flow(service: ServiceDep) -> FlowGraph | None:
    """Graph des aktiven globalen Flows (#28) — ``null``, wenn keiner existiert."""
    return await service.get_active_global_flow()


@router.post(
    "/flow-versions/global",
    response_model=FlowVersionOut,
    status_code=201,
    responses=_errors(400, 401, 403, 422),
)
async def create_global_flow(
    payload: FlowVersionCreate, service: ServiceDep, principal: TypesAdmin
) -> FlowVersionOut:
    """Globalen Flow als neue Version anlegen (#28; gilt für ALLE Antragstypen)."""
    return await service.create_global_flow_version(payload, principal.sub)


# =========================================================================== #
# Rollen / RBAC + Vertretung
# =========================================================================== #
@router.get(
    "/principals",
    response_model=list[PrincipalOut],
    dependencies=[_GREMIEN_OR_USERS],
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
    principal_id: UUID, payload: PrincipalUpdate, service: ServiceDep, principal: UsersAdmin
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
    dependencies=[_ROLES_READ],
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
async def create_role(payload: RoleCreate, service: ServiceDep, principal: RolesAdmin) -> RoleOut:
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
async def delete_role(role_id: UUID, service: ServiceDep, principal: RolesAdmin) -> None:
    """Rolle löschen (#38); ``admin``/``member`` sind geschützt (409)."""
    await service.delete_role(role_id, principal.sub)


@router.get(
    "/role-assignments",
    response_model=list[RoleAssignmentOut],
    dependencies=[_USERS],
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
    payload: RoleAssignmentCreate,
    service: ServiceDep,
    principal: UsersAdmin,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    mailer: AutoMailerDep,
) -> RoleAssignmentOut:
    out = await service.create_role_assignment(payload, principal.sub)
    # Betroffene:n informieren (#4-3, Art role_change/delegation, abwählbar #4-2).
    info = await assignment_mail_info(getattr(service, "session", None), out.id)
    pool = getattr(request.app.state, "arq_pool", None)
    background.add_task(mailer.assignment_changed, settings, info, granted=True, pool=pool)
    return out


@router.patch(
    "/role-assignments/{assignment_id}",
    response_model=RoleAssignmentOut,
    responses=_errors(400, 401, 403, 404, 422),
)
async def update_role_assignment(
    assignment_id: UUID,
    payload: RoleAssignmentUpdate,
    service: ServiceDep,
    principal: UsersAdmin,
) -> RoleAssignmentOut:
    return await service.update_role_assignment(assignment_id, payload, principal.sub)


@router.delete(
    "/role-assignments/{assignment_id}",
    status_code=204,
    responses=_errors(401, 403, 404),
)
async def delete_role_assignment(
    assignment_id: UUID,
    service: ServiceDep,
    principal: UsersAdmin,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    mailer: AutoMailerDep,
) -> Response:
    """Rolle entziehen (#72): Zuweisung löschen (idempotent → 204; unbekannt → 404)."""
    # Mail-Daten VOR dem Löschen einsammeln (#4-3) — danach ist die Zeile weg.
    info = await assignment_mail_info(getattr(service, "session", None), assignment_id)
    await service.delete_role_assignment(assignment_id, principal.sub)
    pool = getattr(request.app.state, "arq_pool", None)
    background.add_task(mailer.assignment_changed, settings, info, granted=False, pool=pool)
    return Response(status_code=204)


@router.get(
    "/group-mappings",
    response_model=list[GroupMappingOut],
    dependencies=[_GROUP_MAPPINGS],
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
    payload: GroupMappingCreate, service: ServiceDep, principal: GroupMappingsAdmin
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
    principal: GroupMappingsAdmin,
) -> GroupMappingOut:
    return await service.update_group_mapping(mapping_id, payload, principal.sub)


@router.delete("/group-mappings/{mapping_id}", status_code=204, responses=_errors(401, 403, 404))
async def delete_group_mapping(
    mapping_id: UUID, service: ServiceDep, principal: GroupMappingsAdmin
) -> None:
    await service.delete_group_mapping(mapping_id, principal.sub)


# =========================================================================== #
# Webhooks (P webhook.manage)
# =========================================================================== #
@router.get(
    "/webhooks",
    response_model=list[WebhookOut],
    dependencies=[_WEBHOOK_OR_FLOW],
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


@router.get(
    "/webhooks/delivery-status",
    response_model=list[WebhookDeliveryStatusOut],
    dependencies=[_WEBHOOK],
    responses=_errors(401, 403),
)
async def list_webhook_delivery_status(
    service: ServiceDep,
) -> list[WebhookDeliveryStatusOut]:
    """Letzter Auslieferungszustand je Webhook (AUD-062): grober Zustand
    (``sent``/``pending``/``dead``/``never``) + grobe Fehlerursachen-Klasse, damit
    ein vertippter/interner Webhook diagnostizierbar ist — ohne aufgelöste interne
    IPs oder Antwort-Bodies zu leaken."""
    return await service.list_webhook_delivery_status()


# =========================================================================== #
# Site-Config / Branding (#21) — Draft/Activate (FE-Kontrakt T-34)
# =========================================================================== #
@router.get(
    "/site-config",
    response_model=SiteConfigOut,
    dependencies=[_SITE],
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
    payload: Branding, service: SiteServiceDep, principal: SiteAdmin
) -> SiteConfigOut:
    """Branding-Draft setzen (Bild-only-Logos, kein Inline-SVG; ungültig → 422)."""
    return await service.put_draft(payload, principal.sub)


@router.post(
    "/site-config/activate",
    response_model=SiteConfigOut,
    responses=_errors(400, 401, 403, 409),
)
async def activate_site_config(service: SiteServiceDep, principal: SiteAdmin) -> SiteConfigOut:
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


# Dynamisches PWA-Manifest (auth-frei, Single Source of Truth = aktive Site-Config).
# Der Edge-Proxy (nginx) mappt das vom Browser verlinkte ``/manifest.webmanifest``
# (frontend/src/index.html) auf diese Route, damit name/short_name dem konfigurierten
# App-Namen folgen. Alle übrigen Felder sind statisch (Icons, theme_color, scope …).
@public_router.get("/manifest.webmanifest", include_in_schema=False)
async def get_manifest(service: SiteServiceDep) -> Response:
    """PWA-Manifest aus der aktiven Branding-Config (application/manifest+json)."""
    import json

    body = json.dumps(await service.manifest(), ensure_ascii=False)
    return Response(
        content=body,
        media_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=300"},
    )
