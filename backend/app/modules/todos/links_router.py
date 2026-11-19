"""Links API router (``/links``, spec 001409).

A link connects any two elements of the kinds of ``LINK_KINDS`` and has no direction
(specs 001400, 001401). Every route needs a principal session (401).

- ``GET /links?kind=&id=`` lists the links of an element that the caller reads (404
  otherwise), with ``canLink`` for the change right on the element.
- ``POST /links`` adds a link between ``a`` and ``b`` and answers the links of ``a``.
  The caller reads both and may change one of them (spec 001404): 422
  ``link_target_not_found`` / ``link_self``, 403 ``link_forbidden``, 409 ``link_exists``
  or ``event_link_taken``.
- ``DELETE /links/{id}`` removes a link from both ends under the same rule.
- ``GET /links/targets`` searches the elements that the caller reads (at most 5 per
  kind), without the excluded element and its links (spec 001408).
- ``GET /links/{id}/view`` is the read sheet of the other end of a card that the caller
  reads (spec 000487).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.deps import require_principal
from app.modules.auth.principal import Principal
from app.modules.todos.access import token_reads
from app.modules.todos.link_service import LinkService
from app.modules.todos.router import ServiceDep
from app.modules.todos.schemas import (
    LinkCreate,
    LinksOut,
    TodoLinkKind,
    TodoLinkTarget,
    TodoLinkView,
)
from app.shared.errors import ProblemDetail

router = APIRouter(prefix="/links", tags=["links"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return dict.fromkeys(codes, _PROBLEM)


Member = Annotated[Principal, Depends(require_principal())]


def get_link_service(service: ServiceDep) -> LinkService:
    """The link service on top of the to-do service, so that the board pings go out."""
    return LinkService(service.session, todos=service)


LinkServiceDep = Annotated[LinkService, Depends(get_link_service)]


@router.get("", response_model=LinksOut, responses=_errors(401, 404, 422))
async def list_links(
    service: LinkServiceDep,
    principal: Member,
    kind: TodoLinkKind,
    target_id: Annotated[UUID, Query(alias="id")],
) -> LinksOut:
    """The links of an element that the caller reads (spec 001407)."""
    return await service.of(kind, target_id, principal)


@router.post(
    "",
    response_model=LinksOut,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(401, 403, 404, 409, 422),
)
async def add_link(payload: LinkCreate, service: LinkServiceDep, principal: Member) -> LinksOut:
    """Link two elements; the answer is the links of ``a``."""
    return await service.add(
        (payload.a.kind, payload.a.id), (payload.b.kind, payload.b.id), principal
    )


@router.get("/targets", response_model=list[TodoLinkTarget], responses=_errors(401, 422))
async def link_targets(
    service: LinkServiceDep,
    principal: Member,
    q: Annotated[str, Query(max_length=200)] = "",
    kind: TodoLinkKind | Literal["all"] = "all",
    exclude_kind: Annotated[TodoLinkKind | None, Query(alias="excludeKind")] = None,
    exclude_id: Annotated[UUID | None, Query(alias="excludeId")] = None,
) -> list[TodoLinkTarget]:
    """Search the elements that the caller may read (at most 5 per kind).

    Below two characters the kind ``todo`` lists the newest cards and any other kind
    nothing (specs 000548, 001408).
    """
    if not token_reads(principal):
        return []
    exclude = (exclude_kind, exclude_id) if exclude_kind and exclude_id else None
    return await service.targets(q, kind, principal, exclude=exclude)


@router.delete(
    "/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_errors(401, 403, 404, 422),
)
async def remove_link(link_id: UUID, service: LinkServiceDep, principal: Member) -> Response:
    """Remove a link from both of its elements (spec 001401)."""
    await service.remove(link_id, principal)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{link_id}/view", response_model=TodoLinkView, responses=_errors(401, 404))
async def get_link_view(link_id: UUID, service: LinkServiceDep, principal: Member) -> TodoLinkView:
    """The read sheet of a link: a card reader reads what the card links (spec 000487)."""
    return await service.view(link_id, principal)
