"""Forms API router.

Endpoints:

* ``GET  /api/application-types/{type_id}/form`` — public; effective form definition
  (+ budget-pot extra fields when ``budget_pot_id`` is chosen).
* ``POST /api/admin/application-types/{type_id}/form-versions`` — permission
  ``form.configure``; new form version (definition validated).

Error responses are declared as ``ProblemDetail`` so the OpenAPI contract is
status/content/schema-conformant.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

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
    """Error status → ``ProblemDetail`` (a hook sets content to problem+json)."""
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
    budget_pot_id: Annotated[UUID | None, Query(alias="budgetPotId")] = None,
) -> EffectiveFormOut:
    """Effective form definition for submission (public)."""
    return await service.get_effective_form(type_id, budget_pot_id)


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
    """Load a type's most recent form version for editing."""
    return await service.get_form_draft(type_id)


@router.post(
    "/admin/application-types/{type_id}/form-versions",
    response_model=FormVersionOut,
    status_code=201,
    # 400 = malformed JSON body (parse error), 422 = schema/definition validation.
    responses=_errors(400, 401, 403, 404, 422),
)
async def create_form_version(
    type_id: UUID,
    payload: FormVersionCreate,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_principal("form.configure"))],
) -> FormVersionOut:
    """Create a new form version (definition validated server-side)."""
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
    """Activate/deactivate a type's form. ``active=false`` locks the type for new
    applications; ``true`` reactivates the latest version."""
    return await service.set_form_active(type_id, payload.active)
