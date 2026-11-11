"""The persons who can act on the current state of an application.

``actionable_principal_emails`` returns everyone who can act on the current state of an
application, by the rule of the task list (``ListingOps.list_tasks``): the person can
read the application and either fire a ``requires_action`` transition (the guard
passes) or still cast a ballot in an open vote. Admins are not included
unconditionally. A member of a Gremium who can only read the application gets no mail.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import groupby

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application
from app.modules.auth.models import (
    GroupMapping,
    Principal,
    Role,
    RoleAssignment,
)
from app.modules.auth.principal import Principal as AuthPrincipal
from app.modules.flow.context import build_base_context, with_actor
from app.modules.flow.models import State, Transition
from app.modules.gremien.models import GremiumMembership
from app.modules.notifications.recipients import principal_rows_with_permission_stmt
from app.shared.guards import GuardContext, GuardError, eval_guard


@dataclass(frozen=True, slots=True)
class ActionableCandidate:
    """A permission-holding principal with the actor facts that guards evaluate."""

    principal_id: uuid.UUID
    sub: str
    email: str
    roles: frozenset[str]
    committees: frozenset[str]


async def _candidates_with_transition_permission(
    session: AsyncSession, now: datetime
) -> list[ActionableCandidate]:
    """Collect the candidates that may fire transitions, with resolved actor facts.

    Roles follow the RBAC resolution of ``resolve_principal``. They combine the role
    assignments with the GroupMapping roles of the OIDC groups of the principal.
    Committees are the gremium ids
    of the active GremiumMembership rows. The function runs a constant number of batch
    queries and makes no per-candidate round trip.
    """
    rows = (
        await session.execute(principal_rows_with_permission_stmt("application.transition"))
    ).all()
    seeds = [
        (pid, sub, email, {str(g) for g in (groups or [])})
        for pid, sub, email, groups in rows
        if email
    ]
    if not seeds:
        return []
    ids = {pid for pid, _sub, _email, _groups in seeds}

    groups_by_pid: dict[uuid.UUID, set[str]] = {
        pid: set(groups) for pid, _sub, _email, groups in seeds
    }
    assignment_rows = (
        await session.execute(
            select(RoleAssignment.principal_id, Role.key)
            .join(Role, Role.id == RoleAssignment.role_id)
            .where(RoleAssignment.principal_id.in_(ids))
        )
    ).all()
    all_groups: set[str] = set().union(*groups_by_pid.values())
    mapping_rows = (
        (
            await session.execute(
                select(GroupMapping.oidc_group, Role.key)
                .join(Role, Role.id == GroupMapping.role_id)
                .where(GroupMapping.oidc_group.in_(all_groups))
            )
        ).all()
        if all_groups
        else []
    )
    membership_rows = (
        await session.execute(
            select(GremiumMembership.principal_id, GremiumMembership.gremium_id).where(
                GremiumMembership.principal_id.in_(ids),
            )
        )
    ).all()
    assigned = _grouped((pid, key) for pid, key in assignment_rows)
    mapped = _grouped((group, key) for group, key in mapping_rows)
    committees = _grouped((pid, str(gremium)) for pid, gremium in membership_rows)

    return [
        ActionableCandidate(
            principal_id=pid,
            sub=sub,
            email=email,
            roles=assigned.get(pid, frozenset())
            | frozenset(role for group in groups_by_pid[pid] for role in mapped.get(group, ())),
            committees=committees.get(pid, frozenset()),
        )
        for pid, sub, email, _groups in seeds
    ]


def _grouped[K, V](pairs: Iterable[tuple[K, V]]) -> dict[K, frozenset[V]]:
    """Group ``(key, value)`` pairs into a map from each key to the set of its values."""
    by_key = sorted(pairs, key=lambda pair: str(pair[0]))
    return {
        key: frozenset(value for _key, value in group)
        for key, group in groupby(by_key, key=lambda pair: pair[0])
    }


def firable_candidates(
    candidates: Sequence[ActionableCandidate],
    transitions: Sequence[Transition],
    base_ctx: GuardContext,
    *,
    created_by: str | None,
) -> list[ActionableCandidate]:
    """Keep the candidates for which at least one transition guard passes.

    The function is pure. It mirrors ``list_tasks`` and ``available_transitions``. A
    candidate counts if and only if one of the given transitions fires under the actor
    context of that candidate. A ``GuardError`` on a single transition counts as not
    firable. This fail-closed rule keeps one bad guard from breaking the whole dispatch.
    """

    def can_fire(candidate: ActionableCandidate) -> bool:
        ctx = with_actor(
            base_ctx,
            roles=candidate.roles,
            committees=candidate.committees,
            is_applicant=created_by is not None and created_by == candidate.sub,
        )
        return any(_fires(transition, ctx) for transition in transitions)

    return [candidate for candidate in candidates if can_fire(candidate)]


def _fires(transition: Transition, ctx: GuardContext) -> bool:
    """Tell whether the guard of the transition passes; a ``GuardError`` counts as no."""
    try:
        return bool(eval_guard(transition.guard, ctx))
    except GuardError:
        return False


async def actionable_principal_emails(
    session: AsyncSession,
    *,
    application_id: uuid.UUID,
    state: State | None,
) -> list[str]:
    """Return the addresses of everyone who can act on the current state now.

    The rule is the one of the task list (``ListingOps.list_tasks``), so a mail goes
    only to a person who has the application as a task:

    * A ``vote`` state: the members of the voting Gremium that an open vote of the
      application still takes a ballot from (``VotingService.can_still_cast``). The
      state alone is no task. While no vote is open, for example before the meeting
      opens it, nobody gets mail.
    * Every other state: the principals for which at least one manual
      ``requires_action`` transition fires (the guard passes) and that can read the
      application (``access.resolve_app_read``, the check of the transition route).

    The transitions are the manual non-branch ones that count as an open task, as in
    ``FlowService._outgoing`` and ``list_tasks``.
    """
    app = await session.scalar(select(Application).where(Application.id == application_id))
    if app is None or app.current_state_id is None:
        return []
    now = datetime.now(UTC)
    if state is not None and state.kind == "vote":
        return await _open_vote_casters(session, app, now)

    transitions = list(
        (
            await session.scalars(
                select(Transition)
                .where(
                    Transition.flow_version_id == app.flow_version_id,
                    Transition.from_state_id == app.current_state_id,
                    Transition.automatic.is_(False),
                    Transition.branch.is_(None),
                    Transition.requires_action.is_(True),
                )
                .order_by(Transition.order)
            )
        ).all()
    )
    if not transitions:
        return []

    base_ctx = await build_base_context(session, app, manual=True)
    candidates = await _candidates_with_transition_permission(session, now)
    firable = firable_candidates(candidates, transitions, base_ctx, created_by=app.created_by)
    readers = await _readers(session, app.id, [c.principal_id for c in firable], now)
    return sorted({c.email for c in firable if c.principal_id in readers})


async def _resolved_principals(
    session: AsyncSession, principal_ids: Sequence[uuid.UUID], now: datetime
) -> list[tuple[uuid.UUID, str, AuthPrincipal]]:
    """Resolve the active principal rows into ``(id, email, Principal)`` triples.

    A deactivated account and an account without an address get no mail.
    """
    from app.modules.auth.rbac import resolve_principal

    if not principal_ids:
        return []
    rows = (
        await session.scalars(
            select(Principal).where(
                Principal.id.in_(principal_ids),
                Principal.active.is_(True),
                Principal.email.is_not(None),
            )
        )
    ).all()
    return [(row.id, str(row.email), await resolve_principal(session, row, now)) for row in rows]


async def _readers(
    session: AsyncSession,
    application_id: uuid.UUID,
    principal_ids: Sequence[uuid.UUID],
    now: datetime,
) -> set[uuid.UUID]:
    """Return the ids of the principals that can read the application.

    The check is ``access.resolve_app_read``, the read check of the transition route,
    so the mail and the route agree on who acts.
    """
    from app.modules.applications.access import resolve_app_read
    from app.shared.errors import ForbiddenError

    async def can_read(principal: AuthPrincipal) -> bool:
        try:
            await resolve_app_read(session, application_id, principal, None)
        except ForbiddenError:
            return False
        return True

    resolved = await _resolved_principals(session, principal_ids, now)
    return {pid for pid, _email, principal in resolved if await can_read(principal)}


async def _open_vote_casters(session: AsyncSession, app: Application, now: datetime) -> list[str]:
    """Return the members that an open vote of the application still takes a ballot from.

    The candidates are the current members of the voting Gremium. The rule is the gate of
    the cast route (``VotingService.can_still_cast``), as in the task list.
    """
    from app.modules.voting.models import Vote
    from app.modules.voting.service import VotingService

    votes = (
        await session.scalars(
            select(Vote).where(Vote.application_id == app.id, Vote.status == "open")
        )
    ).all()
    if not votes or app.vote_gremium_id is None:
        return []
    member_ids = (
        await session.scalars(
            select(GremiumMembership.principal_id).where(
                GremiumMembership.gremium_id == app.vote_gremium_id,
            )
        )
    ).all()
    voting = VotingService(session)

    async def casts_any(principal: AuthPrincipal) -> bool:
        for vote in votes:
            if await voting.can_still_cast(vote, principal, now=now):
                return True
        return False

    resolved = await _resolved_principals(session, list(member_ids), now)
    return sorted({email for _pid, email, principal in resolved if await casts_any(principal)})


async def state_actionable(session: AsyncSession, state: State | None) -> bool:
    """Report whether a state defines an open task.

    Task mail and the reminder worker share this definition. The result is true for a
    ``vote`` state, or for a state with at least one manual ``requires_action``
    transition. A state without such a transition is pass-through or terminal. Nobody
    can act on it, so neither task mail nor a reminder fires.
    """
    if state is None:
        return False
    if state.kind == "vote":
        return True
    count = await session.scalar(
        select(func.count())
        .select_from(Transition)
        .where(
            Transition.from_state_id == state.id,
            Transition.automatic.is_(False),
            Transition.requires_action.is_(True),
        )
    )
    return bool(count)
