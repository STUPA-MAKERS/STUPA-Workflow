"""Admin routes of the config schemas, the Gremien, the Gremium roles and the memberships."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.deps import Principal, SettingsDep, require_principal
from app.modules.admin.router.deps import (
    _ANY_ADMIN_AREA,
    _GREMIEN,
    _GREMIEN_OR_GREMIUM_ROLES,
    _MEMBERSHIP_READERS,
    GremienAdmin,
    GremiumRolesAdmin,
    GremiumRoleServiceDep,
    ServiceDep,
    _errors,
)
from app.modules.admin.schemas import (
    GremiumAdminOut,
    GremiumCreate,
    GremiumMailRecipients,
    GremiumOut,
    GremiumPublicPreview,
    GremiumUpdate,
)
from app.modules.gremien.role_schemas import (
    GremiumMembershipOut,
    GremiumRoleCreate,
    GremiumRoleOut,
    GremiumRoleUpdate,
)
from app.modules.site_config.branding import Branding
from app.shared.config_schemas import export_json_schemas

router = APIRouter(prefix="/admin", tags=["admin"])
authed_router = APIRouter(tags=["gremien"])


@router.get(
    "/config-schemas",
    response_model=dict[str, dict[str, Any]],
    dependencies=[_ANY_ADMIN_AREA],
    responses=_errors(401, 403),
)
async def get_config_schemas() -> dict[str, dict[str, Any]]:
    """Return the JSON schemas (form/flow/voting/branding/...) for the config editors."""
    return export_json_schemas({"Branding": Branding})


@router.get(
    "/committees",
    response_model=list[GremiumAdminOut],
    dependencies=[_GREMIEN],
    responses=_errors(401, 403),
)
async def list_gremien(service: ServiceDep) -> list[GremiumAdminOut]:
    """List the gremien with their member and role counts (admin overview)."""
    return await service.list_gremien_admin()


@router.post(
    "/committees",
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
    "/committees/{gremium_id}",
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
    "/committees/{gremium_id}/public-preview",
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
    "/committees/{gremium_id}",
    status_code=204,
    responses=_errors(401, 403, 404, 409),
)
async def delete_gremium(gremium_id: UUID, service: ServiceDep, principal: GremienAdmin) -> None:
    """Delete a gremium with its meetings, by the rules of the meeting delete."""
    await service.delete_gremium(gremium_id, principal)


@router.get(
    "/committees/{gremium_id}/mail-recipients",
    response_model=GremiumMailRecipients,
    responses=_errors(401, 403, 404),
)
async def get_gremium_mail_recipients(
    gremium_id: UUID, service: ServiceDep, _principal: GremienAdmin
) -> GremiumMailRecipients:
    """Read the gremium's additional protocol recipients."""
    return await service.get_gremium_mail_recipients(gremium_id)


@router.put(
    "/committees/{gremium_id}/mail-recipients",
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
    "/committees/{gremium_id}/roles",
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
    "/committees/{gremium_id}/roles",
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
    "/committee-roles/{role_id}",
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


@router.delete("/committee-roles/{role_id}", status_code=204, responses=_errors(401, 403, 404, 409))
async def delete_gremium_role(
    role_id: UUID, service: GremiumRoleServiceDep, principal: GremiumRolesAdmin
) -> None:
    """Delete a gremium role."""
    await service.delete_role(role_id, principal.sub)


@router.get(
    "/committees/{gremium_id}/memberships",
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
    "/committees",
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
