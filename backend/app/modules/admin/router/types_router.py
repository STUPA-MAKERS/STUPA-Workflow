"""Admin routes of the application types, their groups and the global flow."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.deps import DbSession
from app.modules.admin.router.deps import (
    _FLOW_READABLE,
    _TYPES_OR_FORM,
    FlowVersionAdmin,
    ServiceDep,
    TypesAdmin,
    TypesDeleteAdmin,
    _errors,
)
from app.modules.admin.schemas import (
    ApplicationTypeCreate,
    ApplicationTypeGroupCreate,
    ApplicationTypeGroupOut,
    ApplicationTypeGroupUpdate,
    ApplicationTypeOut,
    ApplicationTypeUpdate,
    FlowVersionCreate,
    FlowVersionOut,
    OrderMove,
)
from app.shared.config_schemas import FlowGraph

router = APIRouter(prefix="/admin", tags=["admin"])


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


@router.post(
    "/application-types/{type_id}/move",
    response_model=list[ApplicationTypeOut],
    responses=_errors(401, 403, 404, 422),
)
async def move_application_type(
    type_id: UUID,
    payload: OrderMove,
    session: DbSession,
    service: ServiceDep,
    principal: TypesAdmin,
) -> list[ApplicationTypeOut]:
    """Move an application type one place up or down inside its group (spec 001183)."""
    result = await service.move_application_type(type_id, payload.by, principal.sub)
    await session.commit()
    return result


@router.get(
    "/application-type-groups",
    response_model=list[ApplicationTypeGroupOut],
    dependencies=[_TYPES_OR_FORM],
    responses=_errors(401, 403),
)
async def list_application_type_groups(service: ServiceDep) -> list[ApplicationTypeGroupOut]:
    """List the groups of Antragsarten in their order (spec 001180)."""
    return await service.list_application_type_groups()


@router.post(
    "/application-type-groups",
    response_model=ApplicationTypeGroupOut,
    status_code=201,
    responses=_errors(401, 403, 422),
)
async def create_application_type_group(
    payload: ApplicationTypeGroupCreate,
    session: DbSession,
    service: ServiceDep,
    principal: TypesAdmin,
) -> ApplicationTypeGroupOut:
    """Create a group of Antragsarten at the end of the order (spec 001180)."""
    result = await service.create_application_type_group(payload, principal.sub)
    await session.commit()
    return result


@router.patch(
    "/application-type-groups/{group_id}",
    response_model=ApplicationTypeGroupOut,
    responses=_errors(401, 403, 404, 422),
)
async def update_application_type_group(
    group_id: UUID,
    payload: ApplicationTypeGroupUpdate,
    session: DbSession,
    service: ServiceDep,
    principal: TypesAdmin,
) -> ApplicationTypeGroupOut:
    """Change the name or the text of a group of Antragsarten."""
    result = await service.update_application_type_group(group_id, payload, principal.sub)
    await session.commit()
    return result


@router.delete(
    "/application-type-groups/{group_id}",
    status_code=204,
    responses=_errors(401, 403, 404),
)
async def delete_application_type_group(
    group_id: UUID, session: DbSession, service: ServiceDep, principal: TypesAdmin
) -> None:
    """Delete a group. Its Antragsarten stay without a group (spec 001180)."""
    await service.delete_application_type_group(group_id, principal.sub)
    await session.commit()


@router.post(
    "/application-type-groups/{group_id}/move",
    response_model=list[ApplicationTypeGroupOut],
    responses=_errors(401, 403, 404, 422),
)
async def move_application_type_group(
    group_id: UUID,
    payload: OrderMove,
    session: DbSession,
    service: ServiceDep,
    principal: TypesAdmin,
) -> list[ApplicationTypeGroupOut]:
    """Move a group of Antragsarten one place up or down (spec 001183)."""
    result = await service.move_application_type_group(group_id, payload.by, principal.sub)
    await session.commit()
    return result


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

    The gate accepts EITHER ``flow.configure`` OR ``admin.types``. It is an
    any-of gate and not a switch to ``flow.configure`` alone, for two reasons.

    1. ``flow.configure`` is the permission the flow editor route gates on. Without
       it in this gate, the holder builds a graph and then gets a 403 on save.
    2. A switch would REMOVE the save from every current ``admin.types`` holder.
       An any-of gate only adds, so no installation loses a capability.

    ``_FLOW_READABLE`` already reads with either key, so the read and the write now
    match.
    """
    return await service.create_global_flow_version(payload, principal.sub)
