"""Admin/config API router.

Endpoints for versioned config CRUD (gremien, application types, the global
flow), RBAC (roles/group-mappings, read-only role assignments), webhooks, corporate-design
variants, config-schemas and site-config/branding, plus a public auth-free
branding read.

RBAC is server-side authoritative. ``require_principal`` answers 401 or 403.
The frontend is only a UX gate. Per-area permissions: ``admin.gremien``,
``admin.types``, ``admin.site``, ``admin.roles``, ``admin.cd_variants``,
``admin.deadlines`` (guest settings, meeting settings), ``webhook.manage``.

``notification-rules`` and ``mail-templates`` live in the notifications module.
``/admin/audit`` lives in audit and the form versions live in forms. This
module does not duplicate them.

Exactly one global flow applies to all application types. A site-config, branding or
"Hilfe & Tickets" save writes a new active version directly, without a draft. The
gremium mappings (OIDC group to gremium membership, OIDC group to gremium role) are
separate from the global group mappings and from each other.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
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
    HelpTicketsSettings,
    LoginSettingsOut,
    LoginSettingsUpdate,
    MeetingSettingsOut,
    MeetingSettingsUpdate,
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
from app.modules.admin.service.cd_variants import SquareLogoRef
from app.modules.admin.site_config_service import SiteConfigService
from app.modules.applications.guest_settings import GuestSettingsService
from app.modules.auth.login_settings import LoginSettingsService
from app.modules.auth.policy import can_view_gremium
from app.modules.livevote.open_window import MeetingSettingsService
from app.modules.notifications.auto import AutoMailer, get_auto_mailer
from app.shared.antiabuse import body_cap
from app.shared.config_schemas import FlowGraph, export_json_schemas
from app.shared.errors import ForbiddenError, NotFoundError, ProblemDetail
from app.shared.filenames import content_disposition

router = APIRouter(prefix="/admin", tags=["admin"])
public_router = APIRouter(tags=["admin"])
#: Router for any authenticated principal WITHOUT admin rights, mounted without the
#: ``/admin`` prefix. It serves the master-data reads that several roles need as
#: dropdown sources.
authed_router = APIRouter(tags=["gremien"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


def get_config_service(session: DbSession, request: Request) -> ConfigService:
    """Build the config service.

    The storage removes the file objects of the to-do comments of a deleted gremium.
    Without MinIO only the rows go.
    """
    return ConfigService(session, storage=getattr(request.app.state, "object_storage", None))


def get_site_config_service(session: DbSession, settings: SettingsDep) -> SiteConfigService:
    """Build the site-config service."""
    return SiteConfigService(session, settings=settings)


def get_gremium_role_service(session: DbSession) -> GremiumRoleService:
    """Build the gremium-role service."""
    return GremiumRoleService(session)


def get_oidc_mapping_service(session: DbSession) -> OidcMappingService:
    """Build the OIDC-mapping service."""
    return OidcMappingService(session)


def get_principal_merge_service(session: DbSession) -> PrincipalMergeService:
    """Build the account-merge service."""
    return PrincipalMergeService(session)


def get_principal_revoke_service(
    session: DbSession, settings: SettingsDep
) -> PrincipalRevokeService:
    """Build the rights-revoke service."""
    return PrincipalRevokeService(session, settings)


def get_cd_variant_service(
    session: DbSession, request: Request, settings: SettingsDep
) -> CdVariantService:
    """Build the CD-variant service.

    Only the logo upload and download touch the object storage. Without MinIO
    (development, contract CI) those two routes answer 503.
    """
    storage = getattr(request.app.state, "object_storage", None)
    return CdVariantService(session, storage=storage, settings=settings)


ServiceDep = Annotated[ConfigService, Depends(get_config_service)]
SiteServiceDep = Annotated[SiteConfigService, Depends(get_site_config_service)]
GremiumRoleServiceDep = Annotated[GremiumRoleService, Depends(get_gremium_role_service)]
OidcMappingServiceDep = Annotated[OidcMappingService, Depends(get_oidc_mapping_service)]
CdVariantServiceDep = Annotated[CdVariantService, Depends(get_cd_variant_service)]
MergeServiceDep = Annotated[PrincipalMergeService, Depends(get_principal_merge_service)]
RevokeServiceDep = Annotated[PrincipalRevokeService, Depends(get_principal_revoke_service)]
AutoMailerDep = Annotated[AutoMailer, Depends(get_auto_mailer)]

#: Content-Length cap for a logo upload, applied before FastAPI buffers the body.
#: Defense in depth next to the nginx cap and the authoritative in-service check.
_enforce_cd_logo_body = body_cap("attachment_max_bytes")

GremienAdmin = Annotated[Principal, Depends(require_principal("admin.gremien"))]
TypesAdmin = Annotated[Principal, Depends(require_principal("admin.types"))]
#: Deleting an application type is destructive, so it has its own permission.
TypesDeleteAdmin = Annotated[Principal, Depends(require_principal("admin.types_delete"))]
SiteAdmin = Annotated[Principal, Depends(require_principal("admin.site"))]
RolesAdmin = Annotated[Principal, Depends(require_principal("admin.roles"))]
WebhookAdmin = Annotated[Principal, Depends(require_principal("webhook.manage"))]
UsersAdmin = Annotated[Principal, Depends(require_principal("admin.users"))]
#: A separate key, because the merge rewrites the history of two accounts and cannot
#: be undone.
MergeAdmin = Annotated[Principal, Depends(require_principal("admin.users.merge"))]
#: Revoke the rights of a person ("Rechte entziehen"). A separate key, because it
#: clears whole Gremien, the pool entries and the delegations of planned meetings. No
#: OAuth scope carries it, so it is a web-only action.
RevokeAdmin = Annotated[Principal, Depends(require_principal("admin.users.revoke_groups"))]
GroupMappingsAdmin = Annotated[Principal, Depends(require_principal("admin.group_mappings"))]
GremiumRolesAdmin = Annotated[Principal, Depends(require_principal("admin.gremium_roles"))]
CdVariantsAdmin = Annotated[Principal, Depends(require_principal("admin.cd_variants"))]
#: The global flow save accepts EITHER key. ``create_global_flow`` gives the reason.
FlowVersionAdmin = Annotated[
    Principal, Depends(require_any_permission("admin.types", "flow.configure"))
]

#: All admin area permissions, for ANY-of reads and the admin landing page.
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
#: The gremien page needs the CD-variant list as a dropdown source.
_CD_VARIANT_OPTIONS = Depends(require_any_permission("admin.gremien", "admin.cd_variants"))
_ANY_ADMIN_AREA = Depends(require_any_permission(*_ALL_ADMIN_AREAS))
#: The gremium-members page reads the gremium roles for the role labels. The group
#: mappings page reads them for its role dropdown.
_GREMIEN_OR_GREMIUM_ROLES = Depends(
    require_any_permission("admin.gremien", "admin.gremium_roles", "admin.group_mappings")
)
#: The principal search serves the user page, the gremium members, the person picker
#: of the substitute pool and the person picker of the account erasure.
_PRINCIPAL_READERS = Depends(
    require_any_permission(
        "admin.gremien", "admin.users", "admin.delegations", "privacy.manage"
    )
)
#: The members page and the "represents" choice of the substitute pool read members.
_MEMBERSHIP_READERS = Depends(require_any_permission("admin.gremien", "admin.delegations"))
#: The flow editor and the budget tree read the global flow. Writes stay on the
#: strict permission.
_FLOW_READABLE = Depends(
    require_any_permission("admin.types", "flow.configure", "budget.structure")
)
#: The roles page, the users page and several config editors read the role list.
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
    """Return the JSON schemas (form/flow/voting/branding/...) for the config editors."""
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
    """Create a gremium."""
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
    """Delete a gremium with its meetings, by the rules of the meeting delete."""
    await service.delete_gremium(gremium_id, principal)


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


@router.get(
    "/gremien/{gremium_id}/roles",
    response_model=list[GremiumRoleOut],
    dependencies=[_GREMIEN_OR_GREMIUM_ROLES],
    responses=_errors(401, 403),
)
async def list_gremium_roles(
    gremium_id: UUID, service: GremiumRoleServiceDep
) -> list[GremiumRoleOut]:
    """List the roles of a gremium."""
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
    """Create a role in a gremium."""
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
    """Update a gremium role."""
    return await service.update_role(role_id, payload, principal.sub)


@router.delete("/gremium-roles/{role_id}", status_code=204, responses=_errors(401, 403, 404, 409))
async def delete_gremium_role(
    role_id: UUID, service: GremiumRoleServiceDep, principal: GremiumRolesAdmin
) -> None:
    """Delete a gremium role."""
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
    the render service and never the browser. The slot ``square`` is the
    exception: PNG, JPEG or WebP only, square, at least 256 x 256 px. It replaces
    the square logo that the variant holds already.
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
    deprecated=True,
)
async def add_cd_variant_vendored_logo(
    variant_id: UUID,
    payload: CdVariantLogoVendoredCreate,
    service: CdVariantServiceDep,
    principal: CdVariantsAdmin,
) -> CdVariantLogoOut:
    """Append a logo that the render service ships. No upload and no object storage involved.

    Deprecated: the admin UI offers only the upload, and the worker job
    `migrate_builtin_cd_logos` turns a vendored row into an upload at its next
    start. The slot ``square`` answers 422.
    """
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
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": content_disposition("attachment", name)},
    )


def _etag_matches(if_none_match: str | None, etag: str) -> bool:
    """Tell if an ``If-None-Match`` header names ``etag`` or the wildcard."""
    if not if_none_match:
        return False
    tags = [tag.strip().removeprefix("W/") for tag in if_none_match.split(",")]
    return "*" in tags or etag in tags


async def _square_logo_response(
    ref: SquareLogoRef, service: CdVariantService, if_none_match: str | None
) -> Response:
    """Answer a square logo inline, or 304 when the client holds the same bytes.

    The type is the sniffed raster type of the row, never SVG (`SquareLogoRef`).
    ``nosniff`` stops the browser from guessing another type, and ``private``
    keeps a shared cache from storing a logo that needs a login.
    """
    headers = {
        "ETag": ref.etag,
        "Cache-Control": "private, max-age=3600",
        "X-Content-Type-Options": "nosniff",
    }
    if _etag_matches(if_none_match, ref.etag):
        return Response(status_code=304, headers=headers)
    data = await service.square_logo_bytes(ref)
    return Response(content=data, media_type=ref.mime, headers=headers)


@router.get(
    "/cd-variant-logos/{logo_id}/square",
    dependencies=[_CD_VARIANTS],
    responses=_errors(401, 403, 404, 503),
    response_class=Response,
)
async def get_cd_variant_square_logo(
    logo_id: UUID,
    service: CdVariantServiceDep,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    """Stream a square logo inline, for the thumbnail on the admin page.

    Only a square row answers. Any other logo answers 404, because a title or footer
    logo can be an SVG, which must never render in the app origin.
    """
    ref = await service.admin_square_logo(logo_id)
    return await _square_logo_response(ref, service, if_none_match)


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


@authed_router.get(
    "/gremien/{gremium_id}/logo",
    responses=_errors(401, 404, 503),
    response_class=Response,
)
async def get_gremium_logo(
    gremium_id: UUID,
    session: DbSession,
    service: CdVariantServiceDep,
    principal: Annotated[Principal, Depends(require_principal())],
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    """Stream the square logo of the CD variant of a Gremium, inline.

    The API streams the bytes itself and never hands out a presigned URL. A
    member of the Gremium, a holder of ``gremium.view_all`` and an admin may read
    it. Everyone else gets 404, the same answer as for a Gremium without a logo,
    so the route does not tell which Gremien exist.
    """
    if not await can_view_gremium(session, principal, gremium_id):
        raise NotFoundError(f"gremium {gremium_id} has no logo")
    ref = await service.gremium_square_logo(gremium_id)
    return await _square_logo_response(ref, service, if_none_match)


@router.get(
    "/application-types",
    response_model=list[ApplicationTypeOut],
    dependencies=[_TYPES_OR_FORM],
    responses=_errors(401, 403),
)
async def list_application_types(service: ServiceDep) -> list[ApplicationTypeOut]:
    """List the application types."""
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
    """Create an application type."""
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
    """Update an application type."""
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


@router.get(
    "/flow-versions/global",
    response_model=FlowGraph | None,
    dependencies=[_FLOW_READABLE],
    responses=_errors(401, 403),
)
async def get_global_flow(service: ServiceDep) -> FlowGraph | None:
    """Return the graph of the active global flow, or ``null``."""
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
    """List the selectable permission keys for the roles UI."""
    return service.list_permissions()


@router.get(
    "/roles",
    response_model=list[RoleOut],
    dependencies=[_ROLES_READ],
    responses=_errors(401, 403),
)
async def list_roles(service: ServiceDep) -> list[RoleOut]:
    """List the global roles with their permissions."""
    return await service.list_roles()


@router.post(
    "/roles",
    response_model=RoleOut,
    status_code=201,
    responses=_errors(400, 401, 403, 409, 422),
)
async def create_role(payload: RoleCreate, service: ServiceDep, principal: RolesAdmin) -> RoleOut:
    """Create a global role."""
    return await service.create_role(payload, principal.sub)


@router.patch(
    "/roles/{role_id}",
    response_model=RoleOut,
    responses=_errors(400, 401, 403, 404, 422),
)
async def update_role(
    role_id: UUID, payload: RoleUpdate, service: ServiceDep, principal: RolesAdmin
) -> RoleOut:
    """Update a global role."""
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
    """List the role assignments."""
    return await service.list_role_assignments()


@router.get(
    "/group-mappings",
    response_model=list[GroupMappingOut],
    dependencies=[_GROUP_MAPPINGS],
    responses=_errors(401, 403),
)
async def list_group_mappings(service: ServiceDep) -> list[GroupMappingOut]:
    """List the OIDC group to global role mappings."""
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
    """Create a group mapping."""
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
    """Update a group mapping."""
    return await service.update_group_mapping(mapping_id, payload, principal.sub)


@router.delete("/group-mappings/{mapping_id}", status_code=204, responses=_errors(401, 403, 404))
async def delete_group_mapping(
    mapping_id: UUID, service: ServiceDep, principal: GroupMappingsAdmin
) -> None:
    """Delete a group mapping."""
    await service.delete_group_mapping(mapping_id, principal.sub)


@router.get(
    "/gremium-membership-mappings",
    response_model=list[GremiumMembershipMappingOut],
    dependencies=[_GROUP_MAPPINGS],
    responses=_errors(401, 403),
)
async def list_gremium_membership_mappings(
    service: OidcMappingServiceDep,
) -> list[GremiumMembershipMappingOut]:
    """List the gremium membership mappings."""
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
    """Update a gremium membership mapping."""
    return await service.update_membership_mapping(mapping_id, payload, principal.sub)


@router.delete(
    "/gremium-membership-mappings/{mapping_id}",
    status_code=204,
    responses=_errors(401, 403, 404),
)
async def delete_gremium_membership_mapping(
    mapping_id: UUID, service: OidcMappingServiceDep, principal: GroupMappingsAdmin
) -> None:
    """Delete a gremium membership mapping."""
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
    """List the gremium role mappings."""
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
    """Update a gremium role mapping."""
    return await service.update_role_mapping(mapping_id, payload, principal.sub)


@router.delete(
    "/gremium-role-mappings/{mapping_id}",
    status_code=204,
    responses=_errors(401, 403, 404),
)
async def delete_gremium_role_mapping(
    mapping_id: UUID, service: OidcMappingServiceDep, principal: GroupMappingsAdmin
) -> None:
    """Delete a gremium role mapping."""
    await service.delete_role_mapping(mapping_id, principal.sub)


@router.get(
    "/webhooks",
    response_model=list[WebhookOut],
    dependencies=[_WEBHOOK_OR_FLOW],
    responses=_errors(401, 403),
)
async def list_webhooks(service: ServiceDep) -> list[WebhookOut]:
    """List the webhooks."""
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
    """Create a webhook."""
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
    """Update a webhook."""
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


DeadlinesAdmin = Annotated[Principal, Depends(require_principal("admin.deadlines"))]


def get_guest_settings_service(session: DbSession) -> GuestSettingsService:
    """Build the guest-settings service."""
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


def get_meeting_settings_service(session: DbSession) -> MeetingSettingsService:
    """Build the meeting-settings service."""
    return MeetingSettingsService(session)


MeetingSettingsServiceDep = Annotated[
    MeetingSettingsService, Depends(get_meeting_settings_service)
]


def get_login_settings_service(session: DbSession) -> LoginSettingsService:
    """Build the login-settings service."""
    return LoginSettingsService(session)


LoginSettingsServiceDep = Annotated[
    LoginSettingsService, Depends(get_login_settings_service)
]


@router.get(
    "/meeting-settings",
    response_model=MeetingSettingsOut,
    dependencies=[Depends(require_principal("admin.deadlines"))],
    responses=_errors(401, 403),
)
async def get_meeting_settings(service: MeetingSettingsServiceDep) -> MeetingSettingsOut:
    """Return the open window of meetings, in minutes before the planned start."""
    row = await service.get()
    await service.session.commit()
    return MeetingSettingsOut.model_validate(row, from_attributes=True)


@router.put(
    "/meeting-settings",
    response_model=MeetingSettingsOut,
    responses=_errors(400, 401, 403, 422),
)
async def put_meeting_settings(
    payload: MeetingSettingsUpdate,
    service: MeetingSettingsServiceDep,
    principal: DeadlinesAdmin,
) -> MeetingSettingsOut:
    """Replace both values.

    ``openLeadMinutes`` is the earliest open before the planned start. Before
    ``confirmLeadMinutes`` the open needs an extra confirmation, so the value must not
    be larger than ``openLeadMinutes`` (422). The change applies to every planned
    meeting at once and writes a ``config_change`` audit entry that the audit log
    cannot revert.
    """
    row = await service.update(
        open_lead_minutes=payload.open_lead_minutes,
        confirm_lead_minutes=payload.confirm_lead_minutes,
        actor=principal.sub,
    )
    return MeetingSettingsOut.model_validate(row, from_attributes=True)


@router.get(
    "/login-settings",
    response_model=LoginSettingsOut,
    dependencies=[_USERS],
    responses=_errors(401, 403),
)
async def get_login_settings(service: LoginSettingsServiceDep) -> LoginSettingsOut:
    """Return the lifetime of an OIDC login in a browser tab and in the installed app."""
    row = await service.get()
    await service.session.commit()
    return LoginSettingsOut.model_validate(row, from_attributes=True)


@router.put(
    "/login-settings",
    response_model=LoginSettingsOut,
    responses=_errors(400, 401, 403, 422),
)
async def put_login_settings(
    payload: LoginSettingsUpdate,
    service: LoginSettingsServiceDep,
    principal: UsersAdmin,
) -> LoginSettingsOut:
    """Replace both lifetimes (days after the last use, 1 to 400).

    A new value applies to every session at its next check at the IdP, so the
    existing sessions follow it too. The change writes a ``config_change`` audit
    entry that the audit log cannot revert. Only a person in the browser may change
    the session policy: an agent token (OAuth scope) gets 403, also with
    ``admin:write``, like the account merge.
    """
    if principal.scope_permissions is not None:
        raise ForbiddenError(
            "Agent tokens cannot change the session lifetimes.", code="cookie_session_required"
        )
    row = await service.update(
        web_session_days=payload.web_session_days,
        pwa_session_days=payload.pwa_session_days,
        actor=principal.sub,
    )
    return LoginSettingsOut.model_validate(row, from_attributes=True)


@router.get(
    "/site-config",
    response_model=SiteConfigOut,
    dependencies=[_SITE],
    responses=_errors(401, 403),
)
async def get_site_config(service: SiteServiceDep) -> SiteConfigOut:
    """Read the active branding config and its version."""
    return await service.get()


@router.put(
    "/site-config",
    response_model=SiteConfigOut,
    responses=_errors(400, 401, 403, 422),
)
async def put_site_config(
    payload: Branding, service: SiteServiceDep, principal: SiteAdmin
) -> SiteConfigOut:
    """Save the branding as the new active version (version bump, audited).

    A logo must be an image. Inline SVG is not allowed. An invalid payload gives 422.
    """
    return await service.save(payload, principal.sub)


@router.get(
    "/help-tickets",
    response_model=HelpTicketsSettings,
    dependencies=[_SITE],
    responses=_errors(401, 403),
)
async def get_help_tickets(service: SiteServiceDep) -> HelpTicketsSettings:
    """Read the help and ticket settings of the active branding."""
    return await service.help_tickets()


@router.put(
    "/help-tickets",
    response_model=HelpTicketsSettings,
    responses=_errors(401, 403, 422),
)
async def put_help_tickets(
    payload: HelpTicketsSettings, service: SiteServiceDep, principal: SiteAdmin
) -> HelpTicketsSettings:
    """Save the help and ticket settings as a new active site-config version.

    A ``wikiUrl`` that is not http(s) or a ``retentionMonths`` out of 1..120 gives
    422. An open branding draft keeps its other changes and takes the new values.
    """
    return await service.put_help_tickets(payload, principal.sub)


@public_router.get("/site-config", response_model=PublicSiteConfigOut)
async def get_public_site_config(
    service: SiteServiceDep, response: Response
) -> PublicSiteConfigOut:
    """Read the active branding config without auth (logo URLs, footer, texts)."""
    response.headers["Cache-Control"] = "public, max-age=300"
    return await service.public()


@public_router.get("/manifest.webmanifest", include_in_schema=False)
async def get_manifest(
    service: SiteServiceDep,
    scheme: Annotated[Literal["light", "dark"], Query()] = "light",
) -> Response:
    """Serve the PWA manifest from the active branding (application/manifest+json).

    The route is auth-free. The edge proxy maps the browser-linked
    ``/manifest.webmanifest`` here, so name and short_name follow the configured app
    name. ``scheme=dark`` gives the dark bar colours; the frontend links it while the
    dark theme is in effect.
    """
    import json

    body = json.dumps(await service.manifest(scheme), ensure_ascii=False)
    return Response(
        content=body,
        media_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=300"},
    )
