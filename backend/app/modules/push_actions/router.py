"""``GET /api/push/actions/{token}``: run the action of a push button.

The Angular service worker runs a background button with ``sendRequest``, which fetches
the URL with a GET and no session. The signed token in the path is therefore the only
right of the request: it names the person, the action and the element, and is valid for
seven days (`notifications.push_tokens`). The route then acts as that person with the
rights the person has now, through the same service checks as the app:

- ``appointment_accept`` / ``appointment_decline``: the answer to a Termin
  (`AppointmentService.answer`: invited, readable, not over).
- ``todo_done``: the card moves into the done column of its board
  (`BoardAccess.can_write`, `TodoService.complete`), with the live pings of the board.

The route needs the feature push (the feature gate) and the feature of its element
(`To-Dos` or `Kalender`). A forged, expired or foreign token, an inactive account and
an element the person cannot reach all answer 404, so the route tells nothing about
other elements. A vote is never an action here, because a vote is secret and needs a
confirmation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, assert_never

from fastapi import APIRouter, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import DbSession, SettingsDep
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.auth.rbac import resolve_principal
from app.modules.calendar.appointments import AppointmentService
from app.modules.notifications.push_tokens import PushActionClaim, PushTokenError, read_action
from app.modules.site_config.features import Feature, FeatureDisabledError, feature_on
from app.modules.todos.live import publish_pings, todo_broker
from app.modules.todos.models import TodoBoard, TodoCard
from app.modules.todos.service import TodoService
from app.shared.errors import NotFoundError, ProblemDetail

router = APIRouter(prefix="/push", tags=["push"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


async def _principal(db: AsyncSession, claim: PushActionClaim) -> Principal:
    row = await db.get(PrincipalRow, claim.principal_id)
    if row is None or not row.active or row.merged_into is not None:
        raise NotFoundError("push action not found")
    return await resolve_principal(db, row, datetime.now(UTC))


async def _todo_done(
    request: Request, db: AsyncSession, principal: Principal, claim: PushActionClaim
) -> None:
    card = await db.get(TodoCard, claim.target_id)
    board = await db.get(TodoBoard, card.board_id) if card is not None else None
    service = TodoService(db)
    actor = await service.access.me(principal)
    if (
        card is None
        or board is None
        or actor is None
        or not await service.access.can_write(board, principal)
    ):
        raise NotFoundError("push action not found")
    if await service.complete(card, board, actor):
        await db.commit()
        await publish_pings(todo_broker(request.app.state), service.pings.drain())


@router.get(
    "/actions/{token}", status_code=204, responses={403: _PROBLEM, 404: _PROBLEM, 409: _PROBLEM}
)
async def run_push_action(
    token: str, request: Request, db: DbSession, settings: SettingsDep
) -> Response:
    """Run the action that the signed token of a push button names (002509)."""
    try:
        claim = read_action(settings.session_secret, token)
    except PushTokenError as exc:
        raise NotFoundError("push action not found") from exc
    principal = await _principal(db, claim)
    needed = Feature.TODOS if claim.action == "todo_done" else Feature.CALENDAR
    if not await feature_on(db, needed):
        raise FeatureDisabledError(frozenset({needed}))
    match claim.action:
        case "appointment_accept" | "appointment_decline":
            await AppointmentService(db).answer(
                principal,
                claim.target_id,
                "accept" if claim.action == "appointment_accept" else "decline",
                now=datetime.now(UTC),
            )
            await db.commit()
        case "todo_done":
            await _todo_done(request, db, principal, claim)
        case _:
            assert_never(claim.action)
    return Response(status_code=204)
