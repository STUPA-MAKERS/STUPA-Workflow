"""Forms-API-Router (T-11).

Endpunkte (api.md §3):

* ``GET  /api/application-types/{type_id}/form`` — öffentlich; effektive
  Form-Definition (+ Topf-Extra-Felder, wenn ``budget_pot_id`` gewählt).
* ``POST /api/admin/application-types/{type_id}/form-versions`` — Permission
  ``form.configure``; neue Form-Version (Definition validiert).

Die DB-Logik liegt in :class:`FormsService` (per ``get_forms_service`` injiziert →
in Tests überschreibbar).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.deps import DbSession, require_principal
from app.modules.forms.schemas import (
    EffectiveFormOut,
    FormVersionCreate,
    FormVersionOut,
)
from app.modules.forms.service import FormsService

router = APIRouter(tags=["forms"])


def get_forms_service(session: DbSession) -> FormsService:
    return FormsService(session)


ServiceDep = Annotated[FormsService, Depends(get_forms_service)]


@router.get("/application-types/{type_id}/form", response_model=EffectiveFormOut)
async def get_effective_form(
    type_id: UUID,
    service: ServiceDep,
    budget_pot_id: Annotated[UUID | None, Query(alias="budgetPotId")] = None,
) -> EffectiveFormOut:
    """Effektive Form-Definition für die Antragstellung (öffentlich)."""
    return await service.get_effective_form(type_id, budget_pot_id)


@router.post(
    "/admin/application-types/{type_id}/form-versions",
    response_model=FormVersionOut,
    status_code=201,
    dependencies=[Depends(require_principal("form.configure"))],
)
async def create_form_version(
    type_id: UUID,
    payload: FormVersionCreate,
    service: ServiceDep,
) -> FormVersionOut:
    """Neue Form-Version anlegen (Definition wird serverseitig validiert)."""
    return await service.create_form_version(type_id, payload)
