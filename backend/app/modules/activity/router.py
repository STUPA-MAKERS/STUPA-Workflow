"""Activity API (specs 001270-001277).

* ``GET /api/activity`` — one step of the events of the items of the caller.
* ``GET /api/activity/status`` — whether an event of another person waits.
* ``POST /api/activity/seen`` — the time up to which the caller has seen the page.

The routes hold no authorization beyond a session or a token. Each source inside the
service reuses the read rule of its own module (spec 001272), so the page shows only what
the caller could read on the detail page of the item. See `service.py`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from app.deps import DbSession, require_principal
from app.modules.activity.schemas import ActivityPage, ActivitySeen, ActivityStatus, ItemKind
from app.modules.activity.service import ActivityService
from app.modules.auth.principal import Principal
from app.shared.errors import ProblemDetail

router = APIRouter(tags=["activity"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}

Reader = Annotated[Principal, Depends(require_principal())]


@router.get(
    "/activity",
    response_model=ActivityPage,
    responses={401: _PROBLEM, 422: _PROBLEM},
)
async def list_activity(
    session: DbSession,
    principal: Reader,
    kind: Annotated[list[ItemKind] | None, Query()] = None,
    own: bool = False,
    cursor: Annotated[str | None, Query(max_length=400)] = None,
    lang: Annotated[str, Query(max_length=8)] = "de",
) -> ActivityPage:
    """Read one step of the page, newest first, 50 events per step.

    ``kind`` limits the page to these kinds of item, ``own`` shows the events of the
    caller too, and ``cursor`` is the ``nextCursor`` of the step before.
    """
    return await ActivityService(session).page(
        principal, kinds=kind or (), own=own, cursor=cursor, lang=lang
    )


@router.get(
    "/activity/status",
    response_model=ActivityStatus,
    responses={401: _PROBLEM},
)
async def activity_status(session: DbSession, principal: Reader) -> ActivityStatus:
    """Tell whether an event of another person waits after the last visit (spec 001275)."""
    return ActivityStatus(hasNew=await ActivityService(session).has_new(principal))


@router.post(
    "/activity/seen",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: _PROBLEM, 422: _PROBLEM},
)
async def mark_activity_seen(session: DbSession, principal: Reader, body: ActivitySeen) -> None:
    """Store the ``readAt`` of a step as the last visit (spec 001275)."""
    await ActivityService(session).mark_seen(principal, body.at)
