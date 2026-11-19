"""Bulk transitions of the Antrag list (specs 001700, 001701, 001703).

A person with ``application.manage`` selects up to `BULK_MAX` Anträge and moves them
into one target state. The options are the targets that every selected Antrag reaches
by a manual transition that the person may fire (`FlowService.available_transitions`).
A transition that puts the Antrag on an agenda needs a meeting per Antrag, so a bulk
action does not offer it.

The fire runs per Antrag in its own transaction and checks the read right, the
transition and its guard again. An error at one Antrag rolls back only that Antrag and
shows in its result entry. A target with the flag ``Bewilligt`` approves each Antrag
with its requested amount.
"""

from __future__ import annotations

from collections.abc import Coroutine, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.access import resolve_app_read
from app.modules.applications.decision import DecisionIn
from app.modules.applications.models import Application
from app.modules.auth.principal import Principal
from app.modules.flow.schemas import (
    BulkAmountOut,
    BulkItemResult,
    BulkTransitionOption,
    TransitionOut,
)
from app.modules.flow.service import FlowService
from app.shared.errors import AppError, ConflictError

#: The error code of an Antrag that has no transition into the chosen target.
BULK_NOT_AVAILABLE = "transition_not_available"


def _title(app: Application) -> str | None:
    """Return the title of an Antrag, or None."""
    value = (app.data or {}).get("title")
    return value.strip() if isinstance(value, str) and value.strip() else None


async def _offered(
    service: FlowService, application_id: UUID, principal: Principal
) -> dict[UUID, TransitionOut]:
    """Return the bulk transitions of one Antrag by target, the first one per target."""
    await resolve_app_read(service.session, application_id, principal, None)
    found = await service.available_transitions(application_id, principal, allow_unconfirmed=False)
    return {t.to_state_id: t for t in reversed(found) if not t.adds_to_agenda}


async def bulk_options(
    service: FlowService, application_ids: Sequence[UUID], principal: Principal
) -> list[BulkTransitionOption]:
    """List the targets that every selected Antrag reaches.

    An Antrag that the person cannot read leaves no common target.
    """
    session = service.session
    ids = list(dict.fromkeys(application_ids))
    try:
        per_app = [await _offered(service, i, principal) for i in ids]
    except AppError:
        return []
    common = set.intersection(*(set(m) for m in per_app))
    first = per_app[0]
    approving = any(first[t].allows_decision for t in common)
    apps = [await session.get(Application, i) for i in ids] if approving else []
    amounts = tuple(
        BulkAmountOut(applicationId=a.id, title=_title(a), amount=a.amount)
        for a in apps
        if a is not None
    )
    return [
        BulkTransitionOption(
            toStateId=t.to_state_id,
            label=t.label,
            color=t.color,
            approves=t.allows_decision,
            amounts=amounts if t.allows_decision else (),
        )
        for t in first.values()
        if t.to_state_id in common
    ]


async def _fire_one(
    service: FlowService,
    application_id: UUID,
    to_state_id: UUID,
    principal: Principal,
    note: str | None,
) -> None:
    """Fire the transition of one Antrag into ``to_state_id``.

    Raises:
        AppError: The Antrag is not readable, has no such transition, or the fire
            fails.
    """
    offered = await _offered(service, application_id, principal)
    transition = offered.get(to_state_id)
    if transition is None:
        raise ConflictError("No transition into this state is available.", code=BULK_NOT_AVAILABLE)
    app = await service.session.get(Application, application_id)
    decision = (
        DecisionIn(approvedAmount=app.amount)
        if transition.allows_decision and app is not None
        else None
    )
    await service.fire(
        application_id,
        transition.id,
        principal,
        note=note,
        allow_unconfirmed=False,
        decision=decision,
    )


async def bulk_fire(
    service: FlowService,
    application_ids: Sequence[UUID],
    to_state_id: UUID,
    principal: Principal,
    *,
    note: str | None = None,
) -> list[BulkItemResult]:
    """Move every selected Antrag into ``to_state_id``, each in its own transaction."""
    return [
        await _result(service.session, i, _fire_one(service, i, to_state_id, principal, note))
        for i in dict.fromkeys(application_ids)
    ]


async def _result(
    session: AsyncSession, application_id: UUID, work: Coroutine[Any, Any, None]
) -> BulkItemResult:
    """Await the work of one Antrag and turn its outcome into a result entry.

    An `AppError` rolls back the open transaction, so the next Antrag starts clean.
    """
    try:
        await work
    except AppError as exc:
        await session.rollback()
        return BulkItemResult(applicationId=application_id, ok=False, code=exc.code, error=str(exc))
    return BulkItemResult(applicationId=application_id, ok=True)
