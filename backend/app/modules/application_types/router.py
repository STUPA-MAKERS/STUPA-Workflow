"""Application-types API router.

`GET /api/application-types` returns a public, paged list of the types offered
for submission. A principal with `form.configure` also gets the inactive types
and the admin-only fields.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.deps import DbSession, Principal, get_current_principal
from app.modules.application_types.schemas import (
    ApplicationTypeListItem,
    ApplicationTypeListQuery,
)
from app.modules.application_types.service import ApplicationTypesService
from app.shared.errors import ProblemDetail
from app.shared.paging import Page

router = APIRouter(tags=["application-types"])

# A principal with this permission sees the inactive types and the admin-only fields.
_ADMIN_PERMISSION = "form.configure"

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Map the given error status codes to `ProblemDetail` responses."""
    return {code: _PROBLEM for code in codes}


def get_application_types_service(session: DbSession) -> ApplicationTypesService:
    return ApplicationTypesService(session)


ServiceDep = Annotated[ApplicationTypesService, Depends(get_application_types_service)]


@router.get(
    "/application-types",
    response_model=Page[ApplicationTypeListItem],
    responses=_errors(422),
)
async def list_application_types(
    service: ServiceDep,
    query: Annotated[ApplicationTypeListQuery, Query()],
    principal: Annotated[Principal | None, Depends(get_current_principal)],
) -> Page[ApplicationTypeListItem]:
    """List the application types (public, admin view with `form.configure`)."""
    is_admin = principal is not None and principal.has(_ADMIN_PERMISSION)
    return await service.list_types(
        lang=query.lang,
        limit=query.limit,
        offset=query.offset,
        include_inactive=is_admin,
        admin=is_admin,
    )
