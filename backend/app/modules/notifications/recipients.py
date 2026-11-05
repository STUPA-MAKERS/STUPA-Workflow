"""Resolve rule ``recipients`` specs to concrete mail addresses from the DB.

Recipient kinds:

``{"kind":"group","ref":"stupa"}``: principals in the OIDC group ``ref``.
``{"kind":"role","ref":"manager"}``: principals with an assignment of role ``ref``.
``{"kind":"gremium","ref":"<id>"}``: current members of Gremium ``ref``.
``{"kind":"applicant"}``: applicant mail of the application that triggered the rule.
``{"kind":"email","ref":"a@b.c"}``: one fixed literal address.
``{"kind":"voteGremium"}``: current members of the Gremium that decides the current vote
of the application (``application.vote_gremium_id``).
``{"kind":"budgetGremium"}``: current members of the effective deciding Gremium of the
cost center of the application.

The resolver removes duplicates and sorts the result. It drops empty addresses.

``actionable_principal_emails`` returns everyone who can act on the current state of an
application, by the rule of the task list (``ListingOps.list_tasks``): the person can
read the application and either fire a ``requires_action`` transition (the guard
passes) or still cast a ballot in an open vote. Admins are not included
unconditionally. A member of a Gremium who can only read the application gets no mail.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import GremiumMembership
from app.modules.applications.models import Applicant, Application
from app.modules.auth.models import (
    GroupMapping,
    Principal,
    Role,
    RoleAssignment,
    RolePermission,
)
from app.modules.auth.principal import Principal as AuthPrincipal
from app.modules.budget.decision import effective_decision_gremium
from app.modules.flow.context import build_base_context, with_actor
from app.modules.flow.models import State, Transition
from app.shared.guards import GuardContext, GuardError, eval_guard

#: Admin role key; it bypasses every permission check. It must match ``Principal.has``,
#: and the recipient resolution runs set-based in SQL, not through ``has``, so the key
#: stays one constant.
ADMIN_ROLE_KEY = "admin"


def _permission_conds(perm: str) -> list[ColumnElement[bool]]:
    """Build the shared WHERE clauses of the permission-holder queries.

    This function mirrors ``Principal.has`` in one place. It applies the admin bypass
    and the RolePermission join, so every resolver builds the identical candidate set.
    """
    return [
        Principal.email.is_not(None),
        Principal.active.is_(True),
        or_(RolePermission.permission == perm, Role.key == ADMIN_ROLE_KEY),
    ]


def principals_with_permission_stmt(perm: str) -> Select[str | None]:
    """Select the mails of active principals that hold ``perm``.

    The principal needs a role assignment. The admin bypass always counts
    (``ADMIN_ROLE_KEY``). The statement builds on ``_permission_conds``, so both
    resolvers stay consistent with ``Principal.has``.
    """
    return (
        select(Principal.email)
        .join(RoleAssignment, RoleAssignment.principal_id == Principal.id)
        .join(Role, Role.id == RoleAssignment.role_id)
        .outerjoin(RolePermission, RolePermission.role_id == Role.id)
        .where(*_permission_conds(perm))
        .distinct()
    )


def principal_rows_with_permission_stmt(
    perm: str,
) -> Select[uuid.UUID, str, str | None, list[str] | None]:
    """Select the identity rows of the permission holders.

    The WHERE clauses match the mail statement. The projection
    ``(id, sub, email, oidc_groups)`` lets the caller resolve the per-principal roles
    and committees that guard evaluation needs. The admin arm stays in the seed and
    mirrors ``Principal.has``. Admins are candidates only. A guard must still fire
    before they receive mail.
    """
    return (
        select(Principal.id, Principal.sub, Principal.email, Principal.oidc_groups)
        .join(RoleAssignment, RoleAssignment.principal_id == Principal.id)
        .join(Role, Role.id == RoleAssignment.role_id)
        .outerjoin(RolePermission, RolePermission.role_id == Role.id)
        .where(*_permission_conds(perm))
        .distinct()
    )


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
        await session.execute(
            principal_rows_with_permission_stmt("application.transition")
        )
    ).all()
    seeds = [
        (pid, sub, email, {str(g) for g in (groups or [])})
        for pid, sub, email, groups in rows
        if email
    ]
    if not seeds:
        return []
    ids = {pid for pid, _sub, _email, _groups in seeds}

    roles_by_pid: dict[uuid.UUID, set[str]] = {pid: set() for pid in ids}
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
    for pid, role_key in assignment_rows:
        roles_by_pid[pid].add(role_key)

    all_groups: set[str] = set().union(*groups_by_pid.values())
    if all_groups:
        mapping_rows = (
            await session.execute(
                select(GroupMapping.oidc_group, Role.key)
                .join(Role, Role.id == GroupMapping.role_id)
                .where(GroupMapping.oidc_group.in_(all_groups))
            )
        ).all()
        mapped_roles: dict[str, set[str]] = {}
        for group, role_key in mapping_rows:
            mapped_roles.setdefault(group, set()).add(role_key)
        for pid, groups in groups_by_pid.items():
            for group in groups:
                roles_by_pid[pid].update(mapped_roles.get(group, ()))

    committees_by_pid: dict[uuid.UUID, set[str]] = {pid: set() for pid in ids}
    membership_rows = (
        await session.execute(
            select(GremiumMembership.principal_id, GremiumMembership.gremium_id).where(
                GremiumMembership.principal_id.in_(ids),
            )
        )
    ).all()
    for pid, membership_gremium in membership_rows:
        committees_by_pid[pid].add(str(membership_gremium))

    return [
        ActionableCandidate(
            principal_id=pid,
            sub=sub,
            email=email,
            roles=frozenset(roles_by_pid[pid]),
            committees=frozenset(committees_by_pid[pid]),
        )
        for pid, sub, email, _groups in seeds
    ]


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
    out: list[ActionableCandidate] = []
    for candidate in candidates:
        ctx = with_actor(
            base_ctx,
            roles=candidate.roles,
            committees=candidate.committees,
            is_applicant=created_by is not None and created_by == candidate.sub,
        )
        for transition in transitions:
            try:
                fires = eval_guard(transition.guard, ctx)
            except GuardError:
                continue
            if fires:
                out.append(candidate)
                break
    return out


@dataclass(slots=True)
class RecipientResolver:
    """Resolve recipient specs against the DB."""

    session: AsyncSession

    async def resolve(
        self,
        specs: list[dict[str, Any]],
        *,
        application_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> list[str]:
        """Resolve all specs into a sorted address list without duplicates.

        An unknown or incomplete spec is ignored, so the rule stays valid.
        """
        now = now or datetime.now(UTC)
        out: set[str] = set()
        for spec in specs:
            kind = spec.get("kind")
            ref = spec.get("ref")
            if kind == "group" and ref:
                out.update(await self._emails_for_group(str(ref)))
            elif kind == "role" and ref:
                out.update(await self._emails_for_role(str(ref)))
            elif kind == "gremium" and ref:
                out.update(await self._emails_for_gremium(str(ref)))
            elif kind == "applicant" and application_id is not None:
                email = await self._applicant_email(application_id)
                if email:
                    out.add(email)
            elif kind == "email" and ref:
                out.add(str(ref).strip())
            elif kind == "voteGremium" and application_id is not None:
                gid = await self.session.scalar(
                    select(Application.vote_gremium_id).where(
                        Application.id == application_id
                    )
                )
                if gid is not None:
                    out.update(await self._emails_for_gremium(str(gid)))
            elif kind == "budgetGremium" and application_id is not None:
                budget_id = await self.session.scalar(
                    select(Application.budget_id).where(Application.id == application_id)
                )
                gid = await effective_decision_gremium(self.session, budget_id)
                if gid is not None:
                    out.update(await self._emails_for_gremium(str(gid)))
            elif kind == "permission" and ref:
                out.update(await self._emails_for_permission(str(ref)))
        return sorted(e for e in out if e)

    async def _emails_for_group(self, group: str) -> list[str]:
        rows = (
            await self.session.scalars(
                select(Principal.email).where(
                    Principal.oidc_groups.contains([group]),
                    Principal.email.is_not(None),
                )
            )
        ).all()
        return [e for e in rows if e]

    async def _emails_for_role(self, role_key: str) -> list[str]:
        stmt = (
            select(Principal.email)
            .join(RoleAssignment, RoleAssignment.principal_id == Principal.id)
            .join(Role, Role.id == RoleAssignment.role_id)
            .where(
                Role.key == role_key,
                Principal.email.is_not(None),
            )
        )
        rows = (await self.session.scalars(stmt)).all()
        return [e for e in rows if e]

    async def _emails_for_gremium(self, gremium_ref: str) -> list[str]:
        """Return the addresses of the gremium members."""
        try:
            gremium_id = uuid.UUID(gremium_ref)
        except (ValueError, AttributeError):
            return []
        stmt = (
            select(Principal.email)
            .join(GremiumMembership, GremiumMembership.principal_id == Principal.id)
            .where(
                GremiumMembership.gremium_id == gremium_id,
                Principal.email.is_not(None),
            )
        )
        rows = (await self.session.scalars(stmt)).all()
        return [e for e in rows if e]

    async def _emails_for_permission(self, perm: str) -> list[str]:
        """Return the addresses of active principals that hold ``perm``.

        A role assignment must grant the permission. The ``admin`` role always
        counts.
        """
        stmt = principals_with_permission_stmt(perm)
        rows = (await self.session.scalars(stmt)).all()
        return [e for e in rows if e]

    async def _applicant_email(self, application_id: uuid.UUID) -> str | None:
        """Return the applicant mail; an anonymized application has none any more."""
        return await self.session.scalar(
            select(Applicant.email).where(
                Applicant.application_id == application_id,
                Applicant.anonymized_at.is_(None),
            )
        )


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
    app = await session.scalar(
        select(Application).where(Application.id == application_id)
    )
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
    firable = firable_candidates(
        candidates, transitions, base_ctx, created_by=app.created_by
    )
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
    return [
        (row.id, str(row.email), await resolve_principal(session, row, now))
        for row in rows
    ]


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

    out: set[uuid.UUID] = set()
    for pid, _email, principal in await _resolved_principals(
        session, principal_ids, now
    ):
        try:
            await resolve_app_read(session, application_id, principal, None)
        except ForbiddenError:
            continue
        out.add(pid)
    return out


async def _open_vote_casters(
    session: AsyncSession, app: Application, now: datetime
) -> list[str]:
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
    out: set[str] = set()
    resolved = await _resolved_principals(session, list(member_ids), now)
    for _pid, email, principal in resolved:
        for vote in votes:
            if await voting.can_still_cast(vote, principal, now=now):
                out.add(email)
                break
    return sorted(out)


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
