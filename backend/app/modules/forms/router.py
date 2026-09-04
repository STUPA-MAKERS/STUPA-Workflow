"""Forms API router.

Endpoints:

* ``GET  /api/application-types/{type_id}/form`` — public. It returns the effective form
  definition.
* ``POST /api/admin/application-types/{type_id}/form-versions`` — needs the
  ``form.configure`` permission. It creates a new form version and validates the
  definition.

Every error response declares ``ProblemDetail``, so the OpenAPI contract matches the
status, the content type and the schema.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from app.deps import DbSession, Principal, require_principal
from app.modules.forms.schemas import (
    EffectiveFormOut,
    FormActiveSet,
    FormDraftOut,
    FormVersionCreate,
    FormVersionOut,
)
from app.modules.forms.service import FormsService
from app.shared.errors import ProblemDetail

router = APIRouter(tags=["forms"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Map each error status to ``ProblemDetail``.

    A response hook sets the content type to problem+json.
    """
    return {code: _PROBLEM for code in codes}


def get_forms_service(session: DbSession) -> FormsService:
    return FormsService(session)


ServiceDep = Annotated[FormsService, Depends(get_forms_service)]


@router.get(
    "/application-types/{type_id}/form",
    response_model=EffectiveFormOut,
    responses=_errors(404),
)
async def get_effective_form(
    type_id: UUID,
    service: ServiceDep,
) -> EffectiveFormOut:
    """Return the effective form definition for a submission (public endpoint)."""
    return await service.get_effective_form(type_id)


@router.get(
    "/admin/application-types/{type_id}/form-versions/latest",
    response_model=FormDraftOut,
    dependencies=[Depends(require_principal("form.configure"))],
    responses=_errors(401, 403, 404),
)
async def get_form_draft(
    type_id: UUID,
    service: ServiceDep,
) -> FormDraftOut:
    """Load the most recent form version of an application type for editing."""
    return await service.get_form_draft(type_id)


@router.post(
    "/admin/application-types/{type_id}/form-versions",
    response_model=FormVersionOut,
    status_code=201,
    # 400 = malformed JSON body (parse error). 422 = schema or definition validation.
    responses=_errors(400, 401, 403, 404, 422),
)
async def create_form_version(
    type_id: UUID,
    payload: FormVersionCreate,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal("form.configure"))],
) -> FormVersionOut:
    """Create a new form version.

    The server validates the definition.
    """
    return await service.create_form_version(type_id, payload, principal.sub)


@router.patch(
    "/admin/application-types/{type_id}/form-active",
    response_model=FormDraftOut,
    dependencies=[Depends(require_principal("form.configure"))],
    responses=_errors(401, 403, 404, 422),
)
async def set_form_active(
    type_id: UUID,
    payload: FormActiveSet,
    service: ServiceDep,
) -> FormDraftOut:
    """Activate or deactivate the form of an application type.

    ``active=false`` locks the type for new applications. ``active=true`` reactivates the
    latest version.
    """
    return await service.set_form_active(type_id, payload.active)
