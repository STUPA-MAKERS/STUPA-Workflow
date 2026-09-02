"""Global search API.

* ``GET /api/search?q=`` — one query, every kind of record the caller may see.

The route holds no authorization beyond requiring a principal. Each source inside the
service reuses the gate of the module it reads from, so the answer can only contain what
the caller could have reached through that module's own list. See `service.py`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.deps import DbSession, get_current_principal
from app.modules.auth.principal import Principal
from app.modules.search.schemas import SearchResults
from app.modules.search.service import SearchService
from app.shared.errors import ProblemDetail, UnauthorizedError

router = APIRouter(tags=["search"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


@router.get(
    "/search",
    response_model=SearchResults,
    responses={401: _PROBLEM},
)
async def search(
    session: DbSession,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    q: Annotated[str, Query(max_length=200)] = "",
    lang: Annotated[str, Query(max_length=8)] = "de",
) -> SearchResults:
    """Search applications, meetings, budget records, committees and people.

    A query shorter than two characters returns nothing rather than an error: the
    palette calls this on every keystroke and the first one is not a mistake.

    The length cap is a DoS bound, not a validation rule. A trigram scan over a very
    long string costs more than any real query ever needs.

    A hit is one flat line, so a translated label is resolved here rather than left for
    the client the way a list item leaves it. `lang` picks the translation.
    """
    if principal is None:
        raise UnauthorizedError("Authentication required.")
    return await SearchService(session).search(q, principal, lang=lang)
