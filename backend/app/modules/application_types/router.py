"""application-types-API-Router (T-25, api.md §3 »applications«).

Endpunkt:

* ``GET /api/application-types`` — öffentlich; gepagte Liste der für die
  Antragstellung anbietbaren Typen. Ein berechtigter Principal
  (``form.configure``) erhält zusätzlich inaktive Typen + Admin-Felder.

Fehler werden als ``ProblemDetail`` deklariert (T-10-Hook → problem+json), damit der
OpenAPI-Contract status/content/schema-konform ist.
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

# Principal mit dieser Permission sieht inaktive Typen + Admin-Zusatzfelder.
_ADMIN_PERMISSION = "form.configure"

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Fehler-Status → ``ProblemDetail`` (content auf problem+json setzt T-10s Hook)."""
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
    """Antragstypen auflisten (öffentlich; Admin-Sicht bei ``form.configure``)."""
    is_admin = principal is not None and principal.has(_ADMIN_PERMISSION)
    return await service.list_types(
        lang=query.lang,
        limit=query.limit,
        offset=query.offset,
        include_inactive=is_admin,
        admin=is_admin,
    )
