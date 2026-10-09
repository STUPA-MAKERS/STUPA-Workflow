"""Admin/config API router.

Endpoints for versioned config CRUD (gremien, application types, the global
flow), RBAC (roles/group-mappings, read-only role assignments), webhooks, corporate-design
variants, config-schemas and site-config/branding, plus a public auth-free
branding read.

RBAC is server-side authoritative. ``require_principal`` answers 401 or 403.
The frontend is only a UX gate. Per-area permissions: ``admin.gremien``,
``admin.types``, ``admin.site``, ``admin.roles``, ``admin.cd_variants``,
``admin.deadlines`` (guest settings), ``webhook.manage``.

``notification-rules`` and ``mail-templates`` live in the notifications module.
``/admin/audit`` lives in audit and the form versions live in forms. This
module does not duplicate them.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Query,
    Request,
    Response,
    UploadFile,
)

from app.deps import (
    DbSession,
    Principal,
    SettingsDep,
    require_any_permission,
    require_principal,
)
from app.modules.admin.branding import Branding
from app.modules.admin.cd_logos import LogoSlot
from app.modules.admin.gremium_roles import GremiumRoleService
from app.modules.admin.oidc_mappings import OidcMappingService
from app.modules.admin.principal_merge import PrincipalMergeService
from app.modules.admin.principal_revoke import PrincipalRevokeService
from app.modules.admin.schemas import (
    ApplicationTypeCreate,
    ApplicationTypeOut,
    ApplicationTypeUpdate,
    CdVariantCreate,
    CdVariantLogoOut,
    CdVariantLogoReorder,
    CdVariantLogoVendoredCreate,
    CdVariantOptionOut,
    CdVariantOut,
    CdVariantUpdate,
    FlowVersionCreate,
    FlowVersionOut,
    GremiumAdminOut,
    GremiumCreate,
    GremiumMailRecipients,
    GremiumMembershipMappingCreate,
    GremiumMembershipMappingOut,
    GremiumMembershipMappingUpdate,
    GremiumMembershipOut,
    GremiumOut,
    GremiumPublicPreview,
    GremiumRoleCreate,
    GremiumRoleMappingCreate,
    GremiumRoleMappingOut,
    GremiumRoleMappingUpdate,
    GremiumRoleOut,
    GremiumRoleUpdate,
    GremiumUpdate,
    GroupMappingCreate,
    GroupMappingOut,
    GroupMappingUpdate,
    GuestSettingsOut,
    GuestSettingsUpdate,
    MergePreviewOut,
    MergeResultOut,
    PrincipalMergeIn,
    PrincipalOut,
    PrincipalRevokeIn,
    PrincipalUpdate,
    PublicSiteConfigOut,
    RevokePreviewOut,
    RevokeResultOut,
    RoleAssignmentOut,
    RoleCreate,
    RoleOut,
    RoleUpdate,
    SiteConfigOut,
    WebhookCreate,
    WebhookDeliveryStatusOut,
    WebhookOut,
    WebhookUpdate,
)
from app.modules.admin.service import CdVariantService, ConfigService
from app.modules.admin.site_config_service import SiteConfigService
from app.modules.applications.guest_settings import GuestSettingsService
from app.modules.notifications.auto import AutoMailer, get_auto_mailer
from app.shared.antiabuse import body_cap
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


def get_oidc_mapping_service(session: DbSession) -> OidcMappingService:
    return OidcMappingService(session)


def get_principal_merge_service(session: DbSession) -> PrincipalMergeService:
    return PrincipalMergeService(session)


def get_principal_revoke_service(
    session: DbSession, settings: SettingsDep
) -> PrincipalRevokeService:
    return PrincipalRevokeService(session, settings)


def get_cd_variant_service(session: DbSession, request: Request) -> CdVariantService:
    # Only the logo upload and download touch the object storage. Without MinIO
    # (development, contract CI) those two routes answer 503.
    storage = getattr(request.app.state, "object_storage", None)
    return CdVariantService(session, storage=storage)


ServiceDep = Annotated[ConfigService, Depends(get_config_service)]
SiteServiceDep = Annotated[SiteConfigService, Depends(get_site_config_service)]
GremiumRoleServiceDep = Annotated[GremiumRoleService, Depends(get_gremium_role_service)]
OidcMappingServiceDep = Annotated[OidcMappingService, Depends(get_oidc_mapping_service)]
CdVariantServiceDep = Annotated[CdVariantService, Depends(get_cd_variant_service)]
MergeServiceDep = Annotated[PrincipalMergeService, Depends(get_principal_merge_service)]
RevokeServiceDep = Annotated[PrincipalRevokeService, Depends(get_principal_revoke_service)]
AutoMailerDep = Annotated[AutoMailer, Depends(get_auto_mailer)]

# Body cap on Content-Length for a logo upload, applied before FastAPI buffers
# the body. It adds defense in depth next to the nginx cap and the authoritative
# in-service size check.
_enforce_cd_logo_body = body_cap("attachment_max_bytes")

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
# Account merge. A separate key: the merge rewrites the history of two accounts and
# cannot be undone, so the user page alone does not grant it.
MergeAdmin = Annotated[Principal, Depends(require_principal("admin.users.merge"))]
# Revoke the rights of a person ("Rechte entziehen"). A separate key: it clears whole
# Gremien, the pool entries and the delegations of planned meetings. No OAuth scope
# carries it, so it is a web-only action.
RevokeAdmin = Annotated[Principal, Depends(require_principal("admin.users.revoke_groups"))]
GroupMappingsAdmin = Annotated[Principal, Depends(require_principal("admin.group_mappings"))]
GremiumRolesAdmin = Annotated[Principal, Depends(require_principal("admin.gremium_roles"))]
CdVariantsAdmin = Annotated[Principal, Depends(require_principal("admin.cd_variants"))]
# The global flow save accepts EITHER key. See `create_global_flow` for the reason.
FlowVersionAdmin = Annotated[
    Principal, Depends(require_any_permission("admin.types", "flow.configure"))
]

# All admin area permissions (for ANY-of reads plus the admin landing page).
_ALL_ADMIN_AREAS = (
    "admin.site",
    "admin.gremien",
    "admin.types",
    "admin.roles",
    "admin.users",
    "admin.group_mappings",
    "admin.gremium_roles",
    "admin.cd_variants",
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
_CD_VARIANTS = Depends(require_principal("admin.cd_variants"))
# The gremien page needs the CD-variant list as a dropdown source. It does not
# hold the matching write permission.
_CD_VARIANT_OPTIONS = Depends(require_any_permission("admin.gremien", "admin.cd_variants"))
# Shared reads serving several admin areas (ANY-of).
_ANY_ADMIN_AREA = Depends(require_any_permission(*_ALL_ADMIN_AREAS))
# The gremium-members subpage (admin.gremien) needs read access to the gremium
# roles for the role labels and to the principals for the names. The group
# mappings page (admin.group_mappings) needs the gremium roles for its role
# dropdown. Neither holds the matching write permission.
_GREMIEN_OR_GREMIUM_ROLES = Depends(
    require_any_permission("admin.gremien", "admin.gremium_roles", "admin.group_mappings")
)
# The principal search serves the user page, the gremium members, the person picker
# of the substitute pool on the delegations page (admin.delegations) and the person
# picker of the account erasure on the privacy page (privacy.manage, D1).
_PRINCIPAL_READERS = Depends(
    require_any_permission(
        "admin.gremien", "admin.users", "admin.delegations", "privacy.manage"
    )
)
# The members of a gremium: the members page (admin.gremien) and the "represents" choice
# of the substitute pool on the delegations page (admin.delegations).
_MEMBERSHIP_READERS = Depends(require_any_permission("admin.gremien", "admin.delegations"))
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
    response_model=list[GremiumAdminOut],
    dependencies=[_GREMIEN],
    responses=_errors(401, 403),
)
async def list_gremien(service: ServiceDep) -> list[GremiumAdminOut]:
    """List the gremien with their member and role counts (admin overview)."""
    return await service.list_gremien_admin()


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
    request: Request,
    settings: SettingsDep,
) -> GremiumOut:
    """Update a gremium.

    A switch of ``protocolsPublic`` from off to on publishes all final protocols
    of the gremium: a job builds the missing public versions (public PDF and
    snapshot). Until the job has built one, that protocol stays hidden.
    """
    was_public = await service.gremium_protocols_public(gremium_id)
    out = await service.update_gremium(gremium_id, payload, principal.sub)
    if out.protocols_public and not was_public:
        from app.modules.protocol.router import schedule_public_backfill

        await schedule_public_backfill(request, service.session, settings, out.id)
    return out


@router.get(
    "/gremien/{gremium_id}/public-preview",
    response_model=GremiumPublicPreview,
    responses=_errors(401, 403, 404),
)
async def gremium_public_preview(
    gremium_id: UUID, service: ServiceDep, _principal: GremienAdmin
) -> GremiumPublicPreview:
    """Count the protocols that the switch ``protocolsPublic`` would publish.

    The admin dialog asks before the save with these numbers.
    """
    return await service.gremium_public_preview(gremium_id)


@router.delete(
    "/gremien/{gremium_id}",
    status_code=204,
    responses=_errors(401, 403, 404, 409),
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


# Gremium roles and the read-only memberships.
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
    dependencies=[_MEMBERSHIP_READERS],
    responses=_errors(401, 403),
)
async def list_gremium_memberships(
    gremium_id: UUID, service: GremiumRoleServiceDep
) -> list[GremiumMembershipOut]:
    """List the memberships that the sync derived from the OIDC groups."""
    return await service.list_memberships(gremium_id)


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


# Corporate-design variants: the logo sets that a Gremium renders its documents
# with. Every route gates on `admin.cd_variants`.
@router.get(
    "/cd-variants",
    response_model=list[CdVariantOut],
    dependencies=[_CD_VARIANTS],
    responses=_errors(401, 403),
)
async def list_cd_variants(service: CdVariantServiceDep) -> list[CdVariantOut]:
    """List the CD variants with their title and footer logos."""
    return await service.list_variants()


@router.post(
    "/cd-variants",
    response_model=CdVariantOut,
    status_code=201,
    responses=_errors(400, 401, 403, 409, 422),
)
async def create_cd_variant(
    payload: CdVariantCreate, service: CdVariantServiceDep, principal: CdVariantsAdmin
) -> CdVariantOut:
    """Create a CD variant. A duplicate key answers 409."""
    return await service.create_variant(payload, principal.sub)


@router.patch(
    "/cd-variants/{variant_id}",
    response_model=CdVariantOut,
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def update_cd_variant(
    variant_id: UUID,
    payload: CdVariantUpdate,
    service: CdVariantServiceDep,
    principal: CdVariantsAdmin,
) -> CdVariantOut:
    """Patch name or base variant. The key is immutable and a change answers 409."""
    return await service.update_variant(variant_id, payload, principal.sub)


@router.delete(
    "/cd-variants/{variant_id}",
    status_code=204,
    responses=_errors(401, 403, 404, 409),
)
async def delete_cd_variant(
    variant_id: UUID, service: CdVariantServiceDep, principal: CdVariantsAdmin
) -> None:
    """Delete a CD variant. A Gremium that still references it answers 409."""
    await service.delete_variant(variant_id, principal.sub)


@router.post(
    "/cd-variants/{variant_id}/logos",
    response_model=CdVariantLogoOut,
    status_code=201,
    dependencies=[Depends(_enforce_cd_logo_body)],
    responses=_errors(401, 403, 404, 413, 415, 422, 503),
)
async def upload_cd_variant_logo(
    variant_id: UUID,
    service: CdVariantServiceDep,
    principal: CdVariantsAdmin,
    slot: Annotated[LogoSlot, Form()],
    file: Annotated[UploadFile, File()],
) -> CdVariantLogoOut:
    """Upload a logo file into the object storage and append it to the slot.

    The server decides the type from the magic bytes. PNG, JPEG, WebP, SVG and
    PDF pass. SVG and PDF pass here, and only here, because these bytes reach
    the LaTeX renderer and never the browser.
    """
    data = await file.read()
    return await service.upload_logo(
        variant_id, data, slot=slot, filename=file.filename, actor=principal.sub
    )


@router.post(
    "/cd-variants/{variant_id}/logos/vendored",
    response_model=CdVariantLogoOut,
    status_code=201,
    responses=_errors(400, 401, 403, 404, 422),
)
async def add_cd_variant_vendored_logo(
    variant_id: UUID,
    payload: CdVariantLogoVendoredCreate,
    service: CdVariantServiceDep,
    principal: CdVariantsAdmin,
) -> CdVariantLogoOut:
    """Append a logo that the render service ships. No upload and no object storage involved."""
    return await service.add_vendored_logo(variant_id, payload, principal.sub)


@router.put(
    "/cd-variants/{variant_id}/logos/order",
    response_model=list[CdVariantLogoOut],
    responses=_errors(400, 401, 403, 404, 422),
)
async def reorder_cd_variant_logos(
    variant_id: UUID,
    payload: CdVariantLogoReorder,
    service: CdVariantServiceDep,
    principal: CdVariantsAdmin,
) -> list[CdVariantLogoOut]:
    """Set the order inside one slot. The list must name every logo of that slot."""
    return await service.reorder_logos(variant_id, payload, principal.sub)


@router.get(
    "/cd-variant-logos/{logo_id}/file",
    dependencies=[_CD_VARIANTS],
    responses=_errors(401, 403, 404, 503),
    response_class=Response,
)
async def get_cd_variant_logo_file(logo_id: UUID, service: CdVariantServiceDep) -> Response:
    """Stream an uploaded logo back from the server.

    Hardening: the route does NOT echo the stored ``mime``. A stored SVG would
    otherwise render inline in the app origin and execute script. The route
    therefore forces ``application/octet-stream`` plus ``Content-Disposition:
    attachment``, the same rule as ``get_invoice_file`` in the budget module.
    """
    data, name = await service.logo_file_bytes(logo_id)
    safe = "".join(c for c in name if c.isprintable() and c not in '"\\\r\n')
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe}"'},
    )


@router.delete(
    "/cd-variant-logos/{logo_id}",
    status_code=204,
    responses=_errors(401, 403, 404),
)
async def delete_cd_variant_logo(
    logo_id: UUID, service: CdVariantServiceDep, principal: CdVariantsAdmin
) -> None:
    """Delete a logo entry. An uploaded object goes with it."""
    await service.delete_logo(logo_id, principal.sub)


@authed_router.get(
    "/cd-variants",
    response_model=list[CdVariantOptionOut],
    dependencies=[_CD_VARIANT_OPTIONS],
    responses=_errors(401, 403),
)
async def list_cd_variant_options(service: CdVariantServiceDep) -> list[CdVariantOptionOut]:
    """Slim CD-variant list (id, key, name) as the source of the Gremium dropdown."""
    return await service.list_variant_options()


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
    payload: FlowVersionCreate, service: ServiceDep, principal: FlowVersionAdmin
) -> FlowVersionOut:
    """Create the global flow as a new version (applies to ALL application types).

    The gate accepts EITHER ``flow.configure`` OR ``admin.types`` (#g7). It is an
    any-of gate and not a switch to ``flow.configure`` alone, for two reasons.

    1. ``flow.configure`` is the permission the flow editor route gates on. Without
       it in this gate, the holder builds a graph and then gets a 403 on save.
    2. A switch would REMOVE the save from every current ``admin.types`` holder.
       An any-of gate only adds, so no installation loses a capability.

    ``_FLOW_READABLE`` already reads with either key, so the read and the write now
    match.
    """
    return await service.create_global_flow_version(payload, principal.sub)


# RBAC: principals, permissions, roles, role assignments and group mappings.
@router.get(
    "/principals",
    response_model=list[PrincipalOut],
    dependencies=[_PRINCIPAL_READERS],
    responses=_errors(401, 403),
)
async def list_principals(
    service: ServiceDep,
    q: Annotated[str | None, Query()] = None,
    last_login_before: Annotated[date | None, Query(alias="lastLoginBefore")] = None,
    include_never: Annotated[bool, Query(alias="includeNever")] = False,
    has_groups: Annotated[bool | None, Query(alias="hasGroups")] = None,
) -> list[PrincipalOut]:
    """List or search the users (OIDC principals) by `sub`, name or e-mail.

    `lastLoginBefore` (ISO date) keeps the people whose last login is before that day;
    `includeNever=true` adds the people who never logged in (alone: only those).
    `hasGroups` keeps the people with (true) or without (false) OIDC groups.
    """
    return await service.search_principals(
        q,
        last_login_before=last_login_before,
        include_never=include_never,
        has_groups=has_groups,
    )


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
    "/principals/{principal_id}/merge-preview",
    response_model=MergePreviewOut,
    responses=_errors(401, 403, 404, 409, 422),
)
async def preview_principal_merge(
    principal_id: UUID,
    service: MergeServiceDep,
    admin: MergeAdmin,
    target_id: Annotated[UUID, Query(alias="targetId")],
) -> MergePreviewOut:
    """Show what a merge of this (old) account into `targetId` would do.

    The answer counts per area the rows that the merge rewrites, combines and removes,
    and lists the real conflicts that block it. It writes nothing.
    """
    return await service.preview(principal_id, target_id, actor=admin.sub)


@router.post(
    "/principals/{principal_id}/merge",
    response_model=MergeResultOut,
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def merge_principal(
    principal_id: UUID,
    payload: PrincipalMergeIn,
    service: MergeServiceDep,
    admin: MergeAdmin,
) -> MergeResultOut:
    """Merge this (old) account into `targetId` in one transaction.

    The merge rewrites the references, combines harmless duplicates and locks the old
    account as a reference to the new one. A real conflict gives 409 `merge_conflict`
    and changes nothing. The audit log stays as it is; the merge itself is the audit
    action `principal_merge`.
    """
    return await service.merge(principal_id, payload.target_id, actor=admin.sub)


@router.get(
    "/principals/{principal_id}/revoke-preview",
    response_model=RevokePreviewOut,
    responses=_errors(401, 403, 404, 409),
)
async def preview_principal_revoke(
    principal_id: UUID, service: RevokeServiceDep, admin: RevokeAdmin
) -> RevokePreviewOut:
    """Show per Gremium and per global role what the person has. Writes nothing.

    Per Gremium: the membership and the gremium role with the SSO groups that cause
    them, the manual role assignments, the pool entries, the delegations in planned
    meetings (revoked) and in live meetings (kept), and the open votes. Each SSO group
    lists every Gremium and global role it leads to.
    """
    return await service.preview(principal_id, actor=admin.sub)


@router.post(
    "/principals/{principal_id}/revoke",
    response_model=RevokeResultOut,
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def revoke_principal(
    principal_id: UUID,
    payload: PrincipalRevokeIn,
    service: RevokeServiceDep,
    admin: RevokeAdmin,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    mailer: AutoMailerDep,
) -> RevokeResultOut:
    """Clear the selected Gremien completely and remove the selected global roles.

    One transaction. A removed SSO group that also leads to an entry that is not
    selected gives 422 `revoke_incomplete`. The own account gives 409
    `revoke_own_account`. The other side of each revoked delegation gets the usual
    mail: the delegate, or the delegator when the person was the delegate.
    """
    out, mails = await service.revoke(principal_id, payload, actor=admin.sub)
    pool = getattr(request.app.state, "arq_pool", None)
    for info in mails:
        background.add_task(mailer.delegation_changed, settings, info, granted=False, pool=pool)
    return out


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


# Gremium mappings: OIDC group → gremium membership and OIDC group → gremium role.
# They are separate from the global group mappings above and from each other.
@router.get(
    "/gremium-membership-mappings",
    response_model=list[GremiumMembershipMappingOut],
    dependencies=[_GROUP_MAPPINGS],
    responses=_errors(401, 403),
)
async def list_gremium_membership_mappings(
    service: OidcMappingServiceDep,
) -> list[GremiumMembershipMappingOut]:
    return await service.list_membership_mappings()


@router.post(
    "/gremium-membership-mappings",
    response_model=GremiumMembershipMappingOut,
    status_code=201,
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def create_gremium_membership_mapping(
    payload: GremiumMembershipMappingCreate,
    service: OidcMappingServiceDep,
    principal: GroupMappingsAdmin,
) -> GremiumMembershipMappingOut:
    """Make the members of an OIDC group members of a gremium.

    The call syncs the memberships of all principals. A duplicate gives 409.
    """
    return await service.create_membership_mapping(payload, principal.sub)


@router.patch(
    "/gremium-membership-mappings/{mapping_id}",
    response_model=GremiumMembershipMappingOut,
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def update_gremium_membership_mapping(
    mapping_id: UUID,
    payload: GremiumMembershipMappingUpdate,
    service: OidcMappingServiceDep,
    principal: GroupMappingsAdmin,
) -> GremiumMembershipMappingOut:
    return await service.update_membership_mapping(mapping_id, payload, principal.sub)


@router.delete(
    "/gremium-membership-mappings/{mapping_id}",
    status_code=204,
    responses=_errors(401, 403, 404),
)
async def delete_gremium_membership_mapping(
    mapping_id: UUID, service: OidcMappingServiceDep, principal: GroupMappingsAdmin
) -> None:
    await service.delete_membership_mapping(mapping_id, principal.sub)


@router.get(
    "/gremium-role-mappings",
    response_model=list[GremiumRoleMappingOut],
    dependencies=[_GROUP_MAPPINGS],
    responses=_errors(401, 403),
)
async def list_gremium_role_mappings(
    service: OidcMappingServiceDep,
) -> list[GremiumRoleMappingOut]:
    return await service.list_role_mappings()


@router.post(
    "/gremium-role-mappings",
    response_model=GremiumRoleMappingOut,
    status_code=201,
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def create_gremium_role_mapping(
    payload: GremiumRoleMappingCreate,
    service: OidcMappingServiceDep,
    principal: GroupMappingsAdmin,
) -> GremiumRoleMappingOut:
    """Give the members of an OIDC group a role in a gremium.

    The role applies only to a member of the gremium of the role. The call syncs the
    memberships of all principals. A duplicate gives 409.
    """
    return await service.create_role_mapping(payload, principal.sub)


@router.patch(
    "/gremium-role-mappings/{mapping_id}",
    response_model=GremiumRoleMappingOut,
    responses=_errors(400, 401, 403, 404, 409, 422),
)
async def update_gremium_role_mapping(
    mapping_id: UUID,
    payload: GremiumRoleMappingUpdate,
    service: OidcMappingServiceDep,
    principal: GroupMappingsAdmin,
) -> GremiumRoleMappingOut:
    return await service.update_role_mapping(mapping_id, payload, principal.sub)


@router.delete(
    "/gremium-role-mappings/{mapping_id}",
    status_code=204,
    responses=_errors(401, 403, 404),
)
async def delete_gremium_role_mapping(
    mapping_id: UUID, service: OidcMappingServiceDep, principal: GroupMappingsAdmin
) -> None:
    await service.delete_role_mapping(mapping_id, principal.sub)


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


@router.delete(
    "/webhooks/{webhook_id}",
    status_code=204,
    responses=_errors(401, 403, 404),
)
async def delete_webhook(
    webhook_id: UUID, service: ServiceDep, principal: WebhookAdmin
) -> None:
    """Delete a webhook and its delivery history.

    The delete cascades to ``webhook_delivery``, so there is no 409 guard. The
    audit log records the removal as ``webhook_config``.
    """
    await service.delete_webhook(webhook_id, principal.sub)


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


# Applications without an account (Z1): the confirmation window and the link
# lifetime. The deadlines page (admin.deadlines) maintains them.
DeadlinesAdmin = Annotated[Principal, Depends(require_principal("admin.deadlines"))]


def get_guest_settings_service(session: DbSession) -> GuestSettingsService:
    return GuestSettingsService(session)


GuestSettingsServiceDep = Annotated[GuestSettingsService, Depends(get_guest_settings_service)]


@router.get(
    "/guest-settings",
    response_model=GuestSettingsOut,
    dependencies=[Depends(require_principal("admin.deadlines"))],
    responses=_errors(401, 403),
)
async def get_guest_settings(service: GuestSettingsServiceDep) -> GuestSettingsOut:
    """Return the confirmation window (hours) and the magic-link lifetime (days)."""
    row = await service.get()
    await service.session.commit()
    return GuestSettingsOut.model_validate(row, from_attributes=True)


@router.put(
    "/guest-settings",
    response_model=GuestSettingsOut,
    responses=_errors(400, 401, 403, 422),
)
async def put_guest_settings(
    payload: GuestSettingsUpdate,
    service: GuestSettingsServiceDep,
    principal: DeadlinesAdmin,
) -> GuestSettingsOut:
    """Replace both values. ``linkTtlDays: null`` gives magic links without an expiry.

    A new ``confirmTtlHours`` applies to the waiting applications at the next
    worker run. A new ``linkTtlDays`` applies to the links requested from now on;
    the existing links keep their expiry. The change writes a ``config_change``
    audit entry that the audit log cannot revert.
    """
    row = await service.update(
        confirm_ttl_hours=payload.confirm_ttl_hours,
        link_ttl_days=payload.link_ttl_days,
        actor=principal.sub,
    )
    return GuestSettingsOut.model_validate(row, from_attributes=True)


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
