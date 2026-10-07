"""The deciding Gremium of a vote state (flow variant B).

A `vote` state names its Gremium in one of two ways:

* `config.gremiumId: "<uuid>"`: a fixed Gremium, or
* `config.gremiumSource: "budget"`: the effective deciding Gremium of the cost center
  of the application (`budget.decision_gremium_id`, own or inherited).

When an application enters a vote state, the engine stores the resolved Gremium in
`application.vote_gremium_id` (the snapshot). When it leaves the vote state, the engine
clears the column. Every reader of "the Gremium of the vote" reads the snapshot, not
the state config.

Fail closed: a state with `gremiumSource: "budget"` whose Gremium does not resolve
must not take the application. `NO_VOTE_GREMIUM` is the problem code of that refusal.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import Gremium
from app.modules.applications.models import Application
from app.modules.budget.decision import effective_decision_gremium
from app.modules.flow.models import State
from app.shared.errors import ConflictError
from app.shared.guards import GREMIUM_SOURCE_BUDGET

NO_VOTE_GREMIUM = "no_vote_gremium"


def _config(state: State) -> dict[str, Any]:
    return state.config if isinstance(state.config, dict) else {}


def gremium_from_budget(state: State | None) -> bool:
    """Tell whether `state` is a vote state that takes its Gremium from the cost center."""
    return (
        state is not None
        and state.kind == "vote"
        and _config(state).get("gremiumSource") == GREMIUM_SOURCE_BUDGET
    )


def fixed_gremium_ref(state: State) -> UUID | None:
    """Return the fixed `config.gremiumId` of a state as a UUID, or `None`."""
    ref = _config(state).get("gremiumId")
    if not isinstance(ref, str) or not ref:
        return None
    try:
        return UUID(ref)
    except ValueError:
        return None


async def resolve_vote_gremium(
    session: AsyncSession, state: State | None, budget_id: UUID | None
) -> UUID | None:
    """Resolve the Gremium that a state gives an application with cost center `budget_id`.

    A non-vote state gives `None`. A fixed `gremiumId` counts only when the Gremium
    exists, so the foreign key of the snapshot always holds.
    """
    if state is None or state.kind != "vote":
        return None
    if gremium_from_budget(state):
        return await effective_decision_gremium(session, budget_id)
    ref = fixed_gremium_ref(state)
    if ref is None:
        return None
    return await session.scalar(select(Gremium.id).where(Gremium.id == ref))


def no_vote_gremium_error() -> ConflictError:
    """Build the 409 of a refused entry into a vote state without a Gremium."""
    return ConflictError(
        "The cost center has no deciding Gremium. Assign a cost center with a "
        "deciding Gremium first.",
        code=NO_VOTE_GREMIUM,
    )


async def snapshot_for_entry(
    session: AsyncSession, state: State | None, budget_id: UUID | None
) -> UUID | None:
    """Resolve the snapshot for an entry into `state`, and fail closed.

    Raises:
        ConflictError: `no_vote_gremium` (409) when `state` takes its Gremium from the
            cost center and none resolves.
    """
    gremium = await resolve_vote_gremium(session, state, budget_id)
    if gremium is None and gremium_from_budget(state):
        raise no_vote_gremium_error()
    return gremium


async def in_budget_vote_state(session: AsyncSession, app: Application) -> bool:
    """Tell whether the application sits in a vote state whose Gremium comes from the budget.

    The cost center of such an application is locked: a change would contradict the
    snapshot of the deciding Gremium.
    """
    if app.current_state_id is None:
        return False
    return gremium_from_budget(await session.get(State, app.current_state_id))
