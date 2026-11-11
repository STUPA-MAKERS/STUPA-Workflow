"""Forms API router.

Endpoints:

* ``GET  /api/application-types/{type_id}/form`` — public. It returns the effective form
  definition.
* ``GET  /api/admin/application-types/{type_id}/form-versions/latest`` and
  ``PATCH /api/admin/application-types/{type_id}/form-active`` — need the
  ``form.configure`` permission.

The route that creates a form version is in `admin.forms_router`, because that write
records a config revision (§S/backend/python/000651).

Every error response declares ``ProblemDetail``, so the OpenAPI contract matches the
status, the content type and the schema.

A 400 means a malformed JSON body (parse error). A 422 means a failed schema or
definition validation.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from app.deps import DbSession, require_principal
from app.modules.forms.schemas import (
    EffectiveFormOut,
    FormActiveSet,
    FormDraftOut,
)
from app.modules.forms.service import BudgetOptions, FormsService
from app.shared.errors import ProblemDetail

router = APIRouter(tags=["forms"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Map each error status to ``ProblemDetail``.

    A response hook sets the content type to problem+json.
    """
    return dict.fromkeys(codes, _PROBLEM)


def get_budget_options() -> BudgetOptions:
    """Return the read of the cost-center options of a form.

    The app overrides this dependency with the read of the module `budget`, because
    `forms` imports no higher module (§S/backend/python/000651).

    Raises:
        RuntimeError: The app did not wire the read.
    """
    raise RuntimeError("The cost-center options of the form are not wired.")


def get_forms_service(
    session: DbSession,
    budget_options: Annotated[BudgetOptions, Depends(get_budget_options)],
) -> FormsService:
    """Build the forms service of a request."""
    return FormsService(session, budget_options)


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
