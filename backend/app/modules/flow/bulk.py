"""Bulk "Status setzen" of the Antrag list (specs 001700, 001701, 001703, 001704).

A person with ``application.manage`` selects up to `BULK_MAX` Anträge and sets them to
one target status. The options are the targets that at least one selected Antrag reaches
by a manual transition that the person may fire (`FlowService.available_transitions`),
each with the Anträge that reach it; the others are skipped.
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
from app.modules.flow.models import State
from app.modules.flow.schemas import (
    BulkAmountOut,
    BulkItemResult,
    BulkTransitionOption,
    TransitionOut,
)
from app.modules.flow.service import FlowService
from app.shared.errors import AppError, ConflictError
from app.shared.i18n import I18nMap

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
    bulk = [t for t in found if not t.adds_to_agenda]
    return {
        target: next(t for t in bulk if t.to_state_id == target)
        for target in dict.fromkeys(t.to_state_id for t in bulk)
    }


async def _offered_or_none(
    service: FlowService, application_id: UUID, principal: Principal
) -> dict[UUID, TransitionOut]:
    """Return the bulk transitions of one Antrag, or none when the person cannot read it."""
    try:
        return await _offered(service, application_id, principal)
    except AppError:
        return {}


async def _state_label(session: AsyncSession, state_id: UUID, fallback: I18nMap) -> I18nMap:
    """Return the name of a state, or the label of the transition when it has none."""
    state = await session.get(State, state_id)
    label = getattr(state, "label_i18n", None)
    return label if isinstance(label, dict) and label else fallback


async def bulk_options(
    service: FlowService, application_ids: Sequence[UUID], principal: Principal
) -> list[BulkTransitionOption]:
    """List every target status that at least one selected Antrag reaches (spec 001704).

    Each option names the Anträge that reach it, so the dialog can say which ones the
    action skips. An Antrag that the person cannot read reaches no target. The label is
    the name of the target state.
    """
    session = service.session
    ids = list(dict.fromkeys(application_ids))
    per_app = [(i, await _offered_or_none(service, i, principal)) for i in ids]
    order = list(dict.fromkeys(target for _, offered in per_app for target in offered))
    first = {t: next(o[t] for _, o in per_app if t in o) for t in order}
    reach = {t: tuple(i for i, o in per_app if t in o) for t in order}
    approving = any(t.allows_decision for t in first.values())
    apps = {i: await session.get(Application, i) for i in ids} if approving else {}
    return [
        BulkTransitionOption(
            toStateId=target,
            label=await _state_label(session, target, first[target].label),
            color=first[target].color,
            approves=first[target].allows_decision,
            amounts=_amounts(apps, reach[target]) if first[target].allows_decision else (),
            applicationIds=reach[target],
        )
        for target in order
    ]


def _amounts(
    apps: dict[UUID, Application | None], reach: tuple[UUID, ...]
) -> tuple[BulkAmountOut, ...]:
    """Return the requested amounts of the Anträge that reach an approving target."""
    return tuple(
        BulkAmountOut(applicationId=a.id, title=_title(a), amount=a.amount)
        for a in (apps.get(i) for i in reach)
        if a is not None
    )


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
