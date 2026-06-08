"""Forms-API-Router (T-11).

Endpunkte (api.md §3):

* ``GET  /api/application-types/{type_id}/form`` — öffentlich; effektive
  Form-Definition (+ Topf-Extra-Felder, wenn ``budget_pot_id`` gewählt).
* ``POST /api/admin/application-types/{type_id}/form-versions`` — Permission
  ``form.configure`` (reale RBAC-Auth aus T-10); neue Form-Version (Definition validiert).

Fehler-Antworten werden als ``ProblemDetail`` deklariert, damit der OpenAPI-Contract
(``use_problem_json_contract``, T-10) status/content/schema-konform ist.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.deps import DbSession, require_principal
from app.modules.forms.schemas import (
    EffectiveFormOut,
    FormDraftOut,
    FormVersionCreate,
    FormVersionOut,
)
from app.modules.forms.service import FormsService
from app.shared.errors import ProblemDetail

router = APIRouter(tags=["forms"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Fehler-Status → ``ProblemDetail`` (content auf problem+json setzt T-10s Hook)."""
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
    """Effektive Form-Definition für die Antragstellung (öffentlich)."""
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
    """Zuletzt angelegte Form-Version eines Typs zum Bearbeiten laden (#13)."""
    return await service.get_form_draft(type_id)


@router.post(
    "/admin/application-types/{type_id}/form-versions",
    response_model=FormVersionOut,
    status_code=201,
    dependencies=[Depends(require_principal("form.configure"))],
    # 400 = malformed JSON body (Parse-Fehler), 422 = Schema-/Definition-Validierung.
    responses=_errors(400, 401, 403, 404, 422),
)
async def create_form_version(
    type_id: UUID,
    payload: FormVersionCreate,
    service: ServiceDep,
) -> FormVersionOut:
    """Neue Form-Version anlegen (Definition wird serverseitig validiert)."""
    return await service.create_form_version(type_id, payload)
