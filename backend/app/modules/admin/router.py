"""Admin/config API router.

Endpoints for versioned config CRUD (gremien, application types, the global
flow), RBAC (roles/role-assignments/group-mappings), webhooks, config-schemas
and site-config/branding, plus a public auth-free branding read.

RBAC is server-side authoritative. ``require_principal`` answers 401 or 403.
The frontend is only a UX gate. Per-area permissions: ``admin.gremien``,
``admin.types``, ``admin.site``, ``admin.roles``, ``webhook.manage``.

``notification-rules`` and ``mail-templates`` live in the notifications module.
``/admin/audit`` lives in audit and the form versions live in forms. This
module does not duplicate them.
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
# Router for any authenticated principal WITHOUT admin rights. It serves the
# master-data reads that several roles need as dropdown sources. It is mounted
# without the `/admin` prefix.
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

# Permission gates. The gate injects the principal object for the audit actor.
GremienAdmin = Annotated[Principal, Depends(require_principal("admin.gremien"))]
TypesAdmin = Annotated[Principal, Depends(require_principal("admin.types"))]
# Deleting an application type is destructive. It needs an own permission,
# separate from admin.types.
TypesDeleteAdmin = Annotated[Principal, Depends(require_principal("admin.types_delete"))]
SiteAdmin = Annotated[Principal, Depends(require_principal("admin.site"))]
RolesAdmin = Annotated[Principal, Depends(require_principal("admin.roles"))]
WebhookAdmin = Annotated[Principal, Depends(require_principal("webhook.manage"))]
# Per-page admin RBAC: the user and access management is gated per admin page.
# ``admin.roles`` covers /admin/roles with the role definitions. The write
# operations of the other pages gate on their own keys.
UsersAdmin = Annotated[Principal, Depends(require_principal("admin.users"))]
GroupMappingsAdmin = Annotated[Principal, Depends(require_principal("admin.group_mappings"))]
GremiumRolesAdmin = Annotated[Principal, Depends(require_principal("admin.gremium_roles"))]

# All admin area permissions (for ANY-of reads plus the admin landing page).
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
# Shared reads serving several admin areas (ANY-of).
_ANY_ADMIN_AREA = Depends(require_any_permission(*_ALL_ADMIN_AREAS))
# The gremium-members subpage (admin.gremien) needs read access to the gremium
# roles for the role dropdown and to the principals for the names and the
# typeahead. It does not hold the matching write permission.
_GREMIEN_OR_GREMIUM_ROLES = Depends(require_any_permission("admin.gremien", "admin.gremium_roles"))
_GREMIEN_OR_USERS = Depends(require_any_permission("admin.gremien", "admin.users"))
# Read gates for pages that need the data of another area only as a selection
# source or a display source. The writes stay on the strict permission. The flow
# editor reads the global flow, the roles, the webhooks and the deadlines. The
# budget tree reads the global flow. The form editor reads the application types.
_FLOW_READABLE = Depends(
    require_any_permission("admin.types", "flow.configure", "budget.structure")
)
# The roles page, the users page (assignment dropdown) and several config editors
# need the role list as a display source.
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


@router.get(
    "/config-schemas",
    response_model=dict[str, dict[str, Any]],
    dependencies=[_ANY_ADMIN_AREA],
    responses=_errors(401, 403),
)
async def get_config_schemas() -> dict[str, dict[str, Any]]:
    """JSON schemas (form/flow/voting/branding/...) for the config editors."""
    return export_json_schemas()


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
    """Read the gremium's additional protocol recipients."""
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
    """Replace the additional protocol recipients.

    The PUT is idempotent. These addresses receive the finalized protocols in
    addition to the active gremium members.
    """
    return await service.set_gremium_mail_recipients(gremium_id, payload, principal.sub)


# Gremium roles: an own role set plus time-bound memberships.
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


@authed_router.get(
    "/gremien",
    response_model=list[GremiumOut],
    responses=_errors(401),
)
async def list_gremien_authed(
    service: ServiceDep,
    _principal: Annotated[Principal, Depends(require_principal())],
) -> list[GremiumOut]:
    """List gremien as master data for any logged-in principal.

    The endpoint serves a dropdown source. It returns read-only master data:
    id, name and variant. Create and update stay on ``admin.gremien``.
    """
    return await service.list_gremien()


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
    """Delete an application type.

    The endpoint needs the own permission ``admin.types_delete``. It answers 409
    while applications of this type still exist.
    """
    await service.delete_application_type(type_id, principal.sub)


# Exactly ONE global flow applies to all application types.
@router.get(
    "/flow-versions/global",
    response_model=FlowGraph | None,
    dependencies=[_FLOW_READABLE],
    responses=_errors(401, 403),
)
async def get_global_flow(service: ServiceDep) -> FlowGraph | None:
    """Graph of the active global flow — ``null`` if none exists."""
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
    """Create the global flow as a new version (applies to ALL application types)."""
    return await service.create_global_flow_version(payload, principal.sub)


# RBAC: principals, permissions, roles, role assignments and group mappings.
@router.get(
    "/principals",
    response_model=list[PrincipalOut],
    dependencies=[_GREMIEN_OR_USERS],
    responses=_errors(401, 403),
)
async def list_principals(
    service: ServiceDep, q: Annotated[str | None, Query()] = None
) -> list[PrincipalOut]:
    """List or search the users (OIDC principals) by `sub`, name or e-mail."""
    return await service.search_principals(q)


@router.patch(
    "/principals/{principal_id}",
    response_model=PrincipalOut,
    responses=_errors(401, 403, 404, 422),
)
async def patch_principal(
    principal_id: UUID, payload: PrincipalUpdate, service: ServiceDep, principal: UsersAdmin
) -> PrincipalOut:
    """Activate or deactivate a user."""
    return await service.set_principal_active(principal_id, payload.active, principal.sub)


@router.get(
    "/permissions",
    response_model=list[str],
    dependencies=[_ROLES],
    responses=_errors(401, 403),
)
async def list_permissions(service: ServiceDep) -> list[str]:
    """Catalog of selectable permission keys for the roles UI."""
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
    """Delete a role. The roles ``admin`` and ``member`` are protected and give 409."""
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
    # Notify the affected user. The user can opt out in the notification preferences.
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
    """Revoke a role and delete the assignment.

    The delete is idempotent and answers 204. An unknown assignment answers 404.
    """
    # Collect the mail data BEFORE the delete. The row is gone afterwards.
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
    """Return the latest delivery state per webhook.

    The response holds a coarse state (``sent``, ``pending``, ``dead`` or
    ``never``) and a coarse failure class. An operator can diagnose a mistyped
    or internal webhook with it. The response leaks no resolved internal IP and
    no response body.
    """
    return await service.list_webhook_delivery_status()


# Site config and branding with draft and activate semantics.
@router.get(
    "/site-config",
    response_model=SiteConfigOut,
    dependencies=[_SITE],
    responses=_errors(401, 403),
)
async def get_site_config(service: SiteServiceDep) -> SiteConfigOut:
    """Active branding config plus current draft plus change flag."""
    return await service.get()


@router.put(
    "/site-config/draft",
    response_model=SiteConfigOut,
    responses=_errors(400, 401, 403, 422),
)
async def put_site_config_draft(
    payload: Branding, service: SiteServiceDep, principal: SiteAdmin
) -> SiteConfigOut:
    """Set the branding draft.

    A logo must be an image. Inline SVG is not allowed. An invalid payload gives 422.
    """
    return await service.put_draft(payload, principal.sub)


@router.post(
    "/site-config/activate",
    response_model=SiteConfigOut,
    responses=_errors(400, 401, 403, 409),
)
async def activate_site_config(service: SiteServiceDep, principal: SiteAdmin) -> SiteConfigOut:
    """Activate the draft as a new active version (version bump, audited)."""
    return await service.activate(principal.sub)


@public_router.get("/site-config", response_model=PublicSiteConfigOut)
async def get_public_site_config(
    service: SiteServiceDep, response: Response
) -> PublicSiteConfigOut:
    """Active branding config without auth (logo URLs, footer, texts)."""
    response.headers["Cache-Control"] = "public, max-age=300"
    return await service.public()


# Dynamic PWA manifest, auth-free. The active site config is the source of truth.
# The edge proxy (nginx) maps the browser-linked ``/manifest.webmanifest`` to this
# route, so name and short_name follow the configured app name.
@public_router.get("/manifest.webmanifest", include_in_schema=False)
async def get_manifest(service: SiteServiceDep) -> Response:
    """PWA manifest from the active branding config (application/manifest+json)."""
    import json

    body = json.dumps(await service.manifest(), ensure_ascii=False)
    return Response(
        content=body,
        media_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=300"},
    )
