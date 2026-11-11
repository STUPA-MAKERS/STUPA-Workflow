"""The admin route that creates a form version.

``POST /api/admin/application-types/{type_id}/form-versions`` needs the
``form.configure`` permission. It creates a new form version and validates the
definition. The route is in `admin`, because the write records a config revision
(§S/backend/python/000651). The URL and the response are those of the forms routes.

A 400 means a malformed JSON body (parse error). A 422 means a failed schema or
definition validation.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from app.deps import DbSession, Principal, require_principal
from app.modules.admin.service.forms import FormVersionWriter
from app.modules.forms.schemas import FormVersionCreate, FormVersionOut
from app.shared.errors import ProblemDetail

router = APIRouter(tags=["forms"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Map each error status to ``ProblemDetail``."""
    return dict.fromkeys(codes, _PROBLEM)


def get_form_version_writer(session: DbSession) -> FormVersionWriter:
    """Build the form version writer of a request."""
    return FormVersionWriter(session)


WriterDep = Annotated[FormVersionWriter, Depends(get_form_version_writer)]


@router.post(
    "/admin/application-types/{type_id}/form-versions",
    response_model=FormVersionOut,
    status_code=201,
    responses=_errors(400, 401, 403, 404, 422),
)
async def create_form_version(
    type_id: UUID,
    payload: FormVersionCreate,
    service: WriterDep,
    principal: Annotated[Principal, Depends(require_principal("form.configure"))],
) -> FormVersionOut:
    """Create a new form version.

    The server validates the definition.
    """
    return await service.create_form_version(type_id, payload, principal.sub)
