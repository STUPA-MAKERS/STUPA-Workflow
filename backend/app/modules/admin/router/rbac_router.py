"""Admin routes of the permissions, roles, role assignments and group mappings."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.modules.admin.router.deps import (
    _GROUP_MAPPINGS,
    _ROLES,
    _ROLES_READ,
    _USERS,
    GroupMappingsAdmin,
    OidcMappingServiceDep,
    RolesAdmin,
    ServiceDep,
    _errors,
)
from app.modules.admin.schemas import (
    GremiumMembershipMappingCreate,
    GremiumMembershipMappingOut,
    GremiumMembershipMappingUpdate,
    GremiumRoleMappingCreate,
    GremiumRoleMappingOut,
    GremiumRoleMappingUpdate,
    GroupMappingCreate,
    GroupMappingOut,
    GroupMappingUpdate,
    RoleAssignmentOut,
    RoleCreate,
    RoleOut,
    RoleUpdate,
)

router = APIRouter(prefix="/admin", tags=["admin"])


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
    "/committee-membership-mappings",
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
    "/committee-membership-mappings",
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
    "/committee-membership-mappings/{mapping_id}",
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
    "/committee-membership-mappings/{mapping_id}",
    status_code=204,
    responses=_errors(401, 403, 404),
)
async def delete_gremium_membership_mapping(
    mapping_id: UUID, service: OidcMappingServiceDep, principal: GroupMappingsAdmin
) -> None:
    """Delete a gremium membership mapping."""
    await service.delete_membership_mapping(mapping_id, principal.sub)


@router.get(
    "/committee-role-mappings",
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
    "/committee-role-mappings",
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
    "/committee-role-mappings/{mapping_id}",
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
    "/committee-role-mappings/{mapping_id}",
    status_code=204,
    responses=_errors(401, 403, 404),
)
async def delete_gremium_role_mapping(
    mapping_id: UUID, service: OidcMappingServiceDep, principal: GroupMappingsAdmin
) -> None:
    """Delete a gremium role mapping."""
    await service.delete_role_mapping(mapping_id, principal.sub)
