"""Routes of the Folgeanträge: the Vorgänger link of an application and the prefill.

The read and edit rules of the applications apply to both applications of a link:

- ``GET .../links`` shows the Vorgänger, the Folgeanträge and the link history. A
  linked application shows only when the reader can open it.
- ``PUT`` and ``DELETE .../predecessor`` need the edit right on the application and on
  the Vorgänger. The change adds no version and leaves the answers as they are.
- ``GET .../prefill`` gives the answers of a readable Vorgänger for a new Antrag. It
  needs a logged-in caller, because a guest has no read scope beyond the own Antrag.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_applicant, get_current_principal
from app.modules.applications.access import (
    Access,
    hidden_pii_keys,
    require_app_edit,
    require_app_read,
    resolve_app_read,
)
from app.modules.applications.router import get_applications_service
from app.modules.applications.schemas import (
    ApplicationLinksOut,
    ApplicationPrefillOut,
    PredecessorSet,
)
from app.modules.applications.service import ApplicationsService
from app.modules.applications.service.links import link_event_out
from app.modules.auth.principal import Applicant, Principal
from app.shared.errors import ForbiddenError, UnauthorizedError

router = APIRouter(tags=["applications"])


ServiceDep = Annotated[ApplicationsService, Depends(get_applications_service)]
PrincipalDep = Annotated[Principal | None, Depends(get_current_principal)]
ApplicantDep = Annotated[Applicant | None, Depends(get_current_applicant)]

_ERRORS: dict[int | str, dict[str, object]] = {
    code: {"description": "problem+json"} for code in (401, 403, 404, 422)
}


async def _can_read(
    db: AsyncSession,
    application_id: UUID,
    principal: Principal | None,
    applicant: Applicant | None,
) -> bool:
    """Tell whether the caller opens an application, by the read rule of the detail."""
    try:
        await resolve_app_read(db, application_id, principal, applicant)
    except (ForbiddenError, UnauthorizedError):
        return False
    return True


async def _links_out(service: ApplicationsService, access: Access) -> ApplicationLinksOut:
    """Build the links of one application as the caller may see them."""
    db = service.session
    application_id = access.application_id
    predecessor = await service.predecessor_of(application_id)
    successors = await service.successors_of(application_id)
    events = await service.link_events(application_id)
    candidates = {
        *([predecessor] if predecessor else []),
        *successors,
        *(ev.predecessor_id for ev in events if ev.predecessor_id),
    }
    readable = {i for i in candidates if await _can_read(db, i, access.principal, access.applicant)}
    shown = await service.linked_out(readable)
    actors = await service.link_event_actors(
        application_id,
        events,
        applicant_view=access.is_applicant_view,
        magic_link_view=access.is_owning_applicant,
    )
    return ApplicationLinksOut(
        predecessor=shown.get(predecessor) if predecessor else None,
        successors=tuple(shown[i] for i in successors if i in shown),
        events=tuple(link_event_out(ev, actors, shown) for ev in events),
    )


@router.get(
    "/applications/{application_id}/links",
    response_model=ApplicationLinksOut,
    responses=_ERRORS,
)
async def get_links(
    service: ServiceDep,
    access: Annotated[Access, Depends(require_app_read)],
) -> ApplicationLinksOut:
    """Read the Vorgänger, the Folgeanträge and the link history of an application.

    A linked application appears only when the caller can open it, also in the history.
    The applicant view names the Gremium as the actor of a change by a member.
    """
    return await _links_out(service, access)


@router.put(
    "/applications/{application_id}/predecessor",
    response_model=ApplicationLinksOut,
    responses=_ERRORS,
)
async def set_predecessor(
    payload: PredecessorSet,
    service: ServiceDep,
    access: Annotated[Access, Depends(require_app_edit)],
    principal: PrincipalDep,
    applicant: ApplicantDep,
) -> ApplicationLinksOut:
    """Set or change the Vorgänger of an application.

    The caller needs the edit right on the application and on the Vorgänger. The
    Vorgänger must have the same application type and must not lead back to the
    application. The answers and the versions stay as they are.
    """
    await require_app_edit(payload.predecessor_id, service.session, principal, applicant)
    await service.set_predecessor(access.application_id, payload.predecessor_id, actor=access.actor)
    return await _links_out(service, access)


@router.delete(
    "/applications/{application_id}/predecessor",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_ERRORS,
)
async def remove_predecessor(
    service: ServiceDep,
    access: Annotated[Access, Depends(require_app_edit)],
    principal: PrincipalDep,
    applicant: ApplicantDep,
) -> Response:
    """Remove the Vorgänger of an application.

    The caller needs the edit right on the application and on the current Vorgänger.
    Without a Vorgänger nothing changes.
    """
    current = await service.predecessor_of(access.application_id)
    if current is not None:
        await require_app_edit(current, service.session, principal, applicant)
        await service.remove_predecessor(access.application_id, actor=access.actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/applications/{application_id}/prefill",
    response_model=ApplicationPrefillOut,
    responses=_ERRORS,
)
async def get_prefill(
    service: ServiceDep,
    access: Annotated[Access, Depends(require_app_read)],
) -> ApplicationPrefillOut:
    """Return the answers of a Vorgänger for a new Antrag of the same type.

    Only a logged-in caller gets them. The answers fit the current form of the type:
    a key that the form lost, an invalid value, a file field and an ``isPII`` field
    that the caller may not read stay out.
    """
    if access.principal is None:
        raise ForbiddenError("A Vorgänger needs a login.")
    hidden = await hidden_pii_keys(service.session, access)
    return await service.prefill(access.application_id, hidden=hidden)
