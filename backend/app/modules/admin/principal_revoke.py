"""Revoke the rights of a person who no longer logs in ("Rechte entziehen").

The SSO groups of a principal come from the last login. A person whom the IdP removed
from a group, and who never logs in again, keeps the memberships and the global roles
of that group. An admin with ``admin.users.revoke_groups`` takes them away here:

- ``preview`` lists per Gremium everything that ties the person to it: the derived
  membership with its gremium role and the SSO groups that cause them, the manual
  gremium role assignments, the pool entries (as substitute or as member), the
  delegations in planned meetings and in live meetings, and the open votes. Then it
  lists each global role with its origin (SSO groups, manual assignments). Each SSO
  group names every Gremium and global role that it leads to.
- ``revoke`` clears the selected Gremien COMPLETELY and removes the selected global
  roles, in ONE transaction. Per Gremium it removes the SSO groups that lead into it
  from ``principal.oidc_groups``, deletes the manual role assignments of the Gremium
  and the pool entries of the person, and revokes the delegations of the planned
  meetings (audit ``delegation_revoke``; the router mails the delegate). A delegation
  of a live meeting stays until the meeting ends. Per global role it removes the SSO
  groups that grant it and deletes the manual global assignments. Then the membership
  sync runs for the person. Optionally the account is deactivated.

A group that also leads to another Gremium or global role is removed for all of them.
The request must therefore name every co-affected entry, else 422 ``revoke_incomplete``
(the dialog selects them automatically). The next login sets ``oidc_groups`` from the
IdP again; manual roles, pool entries and delegations do not come back.

The implicit global role ``member`` (every person holds it) is never listed and never
deleted.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Select, case, delete, exists, func, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.membership_sync import sync_principal_memberships
from app.modules.admin.models import (
    Gremium,
    GremiumMembership,
    GremiumMembershipMapping,
    GremiumRole,
    GremiumRoleMapping,
)
from app.modules.admin.schemas import (
    PrincipalRevokeIn,
    RevokeAssignmentOut,
    RevokeDelegationOut,
    RevokeGlobalRoleOut,
    RevokeGremiumOut,
    RevokeGroupOut,
    RevokeMembershipOut,
    RevokePoolEntryOut,
    RevokePreviewOut,
    RevokePrincipalOut,
    RevokeResultOut,
)
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import AuditService
from app.modules.auth.identity import refs_by_id, refs_by_sub
from app.modules.auth.models import GroupMapping, Role, RoleAssignment
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.delegations.models import DelegationSubstitute, MeetingDelegation
from app.modules.delegations.pool import pool_entries_of, pool_principals_stmt
from app.modules.livevote.models import Meeting
from app.modules.notifications.auto import DelegationMailInfo, meeting_delegation_mail_info
from app.modules.voting.models import Ballot, Vote, VotedMarker
from app.shared.errors import ConflictError, FieldError, NotFoundError, ValidationProblem

# The implicit global role of every person. It is no right to take away.
IMPLICIT_ROLE_KEY = "member"
# The meeting states in which a delegation still matters. A planned meeting has not
# started: its delegations are revoked. A live meeting keeps them until it ends.
_PLANNED = "planned"
_LIVE = "live"


@dataclass(frozen=True, slots=True)
class RoleInfo:
    """A global role or a gremium role: id, key and the i18n label."""

    id: UUID
    key: str
    label: dict[str, str]


@dataclass(frozen=True, slots=True)
class MembershipFact:
    gremium_id: UUID
    role: RoleInfo


@dataclass(frozen=True, slots=True)
class AssignmentFact:
    id: UUID
    role: RoleInfo
    gremium_id: UUID | None
    granted_by: str | None
    valid_from: datetime | None
    valid_until: datetime | None


@dataclass(frozen=True, slots=True)
class PoolFact:
    id: UUID
    gremium_id: UUID
    member_id: UUID | None
    substitute_id: UUID


@dataclass(frozen=True, slots=True)
class DelegationFact:
    id: UUID
    gremium_id: UUID
    meeting_id: UUID
    meeting_title: str
    meeting_date: date | None
    meeting_status: str
    delegator_id: UUID
    delegate_id: UUID
    voting: bool


@dataclass(slots=True)
class Snapshot:
    """Everything the preview and the revoke need, loaded once (``_snapshot``).

    The pure functions below (``group_targets``, ``tied_gremien``, ``held_roles``,
    ``build_preview``, ``plan_revoke``) work on it without a database.
    """

    principal_id: UUID
    groups: list[str]
    memberships: list[MembershipFact] = field(default_factory=list)
    assignments: list[AssignmentFact] = field(default_factory=list)
    pool: list[PoolFact] = field(default_factory=list)
    delegations: list[DelegationFact] = field(default_factory=list)
    # (group, gremium) of the membership mappings of the person's groups.
    membership_maps: list[tuple[str, UUID]] = field(default_factory=list)
    # (group, gremium, gremium role) of the role mappings of the person's groups.
    role_maps: list[tuple[str, UUID, UUID]] = field(default_factory=list)
    # (group, global role) of the group mappings of the person's groups.
    group_maps: list[tuple[str, RoleInfo]] = field(default_factory=list)
    gremium_names: dict[UUID, str] = field(default_factory=dict)
    # Display names of the other people (pool, delegations), by principal id.
    names: dict[UUID, str | None] = field(default_factory=dict)
    # Display names of the grantors of the assignments, by `sub`.
    grantor_names: dict[str, str | None] = field(default_factory=dict)
    # Open votes per Gremium that still wait for a ballot of the person.
    open_tasks: dict[UUID, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RevokePlan:
    """What a revoke changes. ``plan_revoke`` builds it; ``revoke`` applies it."""

    gremium_ids: list[UUID]
    global_role_ids: list[UUID]
    removed_groups: list[str]
    assignments: list[AssignmentFact]
    pool: list[PoolFact]
    delegations: list[DelegationFact]
    kept_live: int


# -- Pure logic ---------------------------------------------------------------------


def held_roles(snap: Snapshot) -> dict[UUID, RoleInfo]:
    """The global roles of the person (groups and manual assignments), without ``member``."""
    roles: dict[UUID, RoleInfo] = {}
    for _group, role in snap.group_maps:
        roles[role.id] = role
    for a in snap.assignments:
        if a.gremium_id is None:
            roles[a.role.id] = a.role
    return {rid: r for rid, r in roles.items() if r.key != IMPLICIT_ROLE_KEY}


def tied_gremien(snap: Snapshot) -> set[UUID]:
    """Every Gremium the person is tied to by a membership, a group, a row or a delegation."""
    tied = {m.gremium_id for m in snap.memberships}
    tied |= {gid for _group, gid in snap.membership_maps}
    tied |= {a.gremium_id for a in snap.assignments if a.gremium_id is not None}
    tied |= {p.gremium_id for p in snap.pool}
    tied |= {d.gremium_id for d in snap.delegations}
    return tied


def group_targets(snap: Snapshot) -> dict[str, tuple[set[UUID], set[UUID]]]:
    """Map each SSO group of the person to the Gremien and global roles it leads to.

    A membership mapping always counts. A role mapping counts only for a Gremium the
    person is tied to: elsewhere the role has no effect. The role ``member`` never
    counts. Groups that lead nowhere are left out.
    """
    tied = tied_gremien(snap)
    own = set(snap.groups)
    out: dict[str, tuple[set[UUID], set[UUID]]] = {}

    def entry(group: str) -> tuple[set[UUID], set[UUID]]:
        return out.setdefault(group, (set(), set()))

    for group, gid in snap.membership_maps:
        if group in own:
            entry(group)[0].add(gid)
    for group, gid, _role_id in snap.role_maps:
        if group in own and gid in tied:
            entry(group)[0].add(gid)
    for group, role in snap.group_maps:
        if group in own and role.key != IMPLICIT_ROLE_KEY:
            entry(group)[1].add(role.id)
    return out


def _ordered_groups(snap: Snapshot, wanted: Iterable[str]) -> list[str]:
    """The groups of ``wanted`` in the order of the person's group list."""
    keep = set(wanted)
    return [g for g in snap.groups if g in keep]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _assignment_out(a: AssignmentFact, snap: Snapshot) -> RevokeAssignmentOut:
    granted = a.granted_by
    if granted and granted in snap.grantor_names:
        granted = snap.grantor_names[granted] or granted
    return RevokeAssignmentOut(
        id=a.id,
        role_id=a.role.id,
        role_key=a.role.key,
        role_label=a.role.label,
        granted_by=granted,
        valid_from=_iso(a.valid_from),
        valid_until=_iso(a.valid_until),
    )


def _pool_out(p: PoolFact, snap: Snapshot) -> RevokePoolEntryOut:
    return RevokePoolEntryOut(
        id=p.id,
        as_substitute=p.substitute_id == snap.principal_id,
        gremium_wide=p.member_id is None,
        member_name=snap.names.get(p.member_id) if p.member_id is not None else None,
        substitute_name=snap.names.get(p.substitute_id),
    )


def _delegation_out(d: DelegationFact, snap: Snapshot) -> RevokeDelegationOut:
    as_delegator = d.delegator_id == snap.principal_id
    other = d.delegate_id if as_delegator else d.delegator_id
    return RevokeDelegationOut(
        id=d.id,
        meeting_id=d.meeting_id,
        meeting_title=d.meeting_title,
        meeting_date=d.meeting_date.isoformat() if d.meeting_date else None,
        as_delegator=as_delegator,
        other_name=snap.names.get(other),
        voting=d.voting,
    )


def _membership_out(snap: Snapshot, gid: UUID) -> RevokeMembershipOut | None:
    membership = next((m for m in snap.memberships if m.gremium_id == gid), None)
    if membership is None:
        return None
    causes = {g for g, mid in snap.membership_maps if mid == gid}
    causes |= {g for g, _mid, rid in snap.role_maps if rid == membership.role.id}
    return RevokeMembershipOut(
        role_key=membership.role.key,
        role_label=membership.role.label,
        groups=_ordered_groups(snap, causes),
    )


def build_preview(
    snap: Snapshot, row: PrincipalRow, *, is_self: bool
) -> RevokePreviewOut:
    """Build the preview of the dialog from the snapshot. Writes nothing."""
    targets = group_targets(snap)
    gremien: list[RevokeGremiumOut] = []
    for gid in tied_gremien(snap):
        gremien.append(
            RevokeGremiumOut(
                gremium_id=gid,
                name=snap.gremium_names.get(gid, ""),
                membership=_membership_out(snap, gid),
                groups=_ordered_groups(
                    snap, (g for g, (gs, _rs) in targets.items() if gid in gs)
                ),
                assignments=[
                    _assignment_out(a, snap) for a in snap.assignments if a.gremium_id == gid
                ],
                pool_entries=[_pool_out(p, snap) for p in snap.pool if p.gremium_id == gid],
                planned_delegations=[
                    _delegation_out(d, snap)
                    for d in snap.delegations
                    if d.gremium_id == gid and d.meeting_status == _PLANNED
                ],
                live_delegations=[
                    _delegation_out(d, snap)
                    for d in snap.delegations
                    if d.gremium_id == gid and d.meeting_status == _LIVE
                ],
                open_tasks=snap.open_tasks.get(gid, 0),
            )
        )
    gremien.sort(key=lambda g: (g.name.casefold(), str(g.gremium_id)))
    roles = [
        RevokeGlobalRoleOut(
            role_id=role.id,
            role_key=role.key,
            role_label=role.label,
            groups=_ordered_groups(
                snap, (g for g, (_gs, rs) in targets.items() if role.id in rs)
            ),
            assignments=[
                _assignment_out(a, snap)
                for a in snap.assignments
                if a.gremium_id is None and a.role.id == role.id
            ],
        )
        for role in held_roles(snap).values()
    ]
    roles.sort(key=lambda r: (r.role_key, str(r.role_id)))
    groups = [
        RevokeGroupOut(
            group=g,
            gremium_ids=sorted(targets[g][0], key=str),
            global_role_ids=sorted(targets[g][1], key=str),
        )
        for g in _ordered_groups(snap, targets)
    ]
    return RevokePreviewOut(
        principal=RevokePrincipalOut(
            id=row.id,
            display_name=row.display_name,
            email=row.email,
            last_login=_iso(row.last_login),
            active=row.active is not False,
        ),
        gremien=gremien,
        global_roles=roles,
        groups=groups,
        is_self=is_self,
    )


def plan_revoke(
    snap: Snapshot,
    gremium_ids: Iterable[UUID],
    global_role_ids: Iterable[UUID],
    *,
    deactivate: bool,
) -> RevokePlan:
    """Check the selection against the snapshot and list what the revoke changes.

    Raises:
        ValidationProblem: Nothing is selected and ``deactivate`` is off
            (``revoke_empty``); a selected Gremium or role is not one of the person
            (``revoke_unknown_target``); or a removed group also leads to an entry
            that is not selected (``revoke_incomplete``; ``errors`` name each missing
            id under ``gremiumIds`` or ``globalRoleIds``) (422).
    """
    gremien = list(dict.fromkeys(gremium_ids))
    roles = list(dict.fromkeys(global_role_ids))
    if not gremien and not roles and not deactivate:
        raise ValidationProblem(
            "Select at least one Gremium or role, or deactivate the account.",
            code="revoke_empty",
        )
    tied = tied_gremien(snap)
    held = held_roles(snap)
    unknown = [
        FieldError(field="gremiumIds", msg=str(g)) for g in gremien if g not in tied
    ] + [FieldError(field="globalRoleIds", msg=str(r)) for r in roles if r not in held]
    if unknown:
        raise ValidationProblem(
            "The person has no tie to a selected Gremium or role.",
            code="revoke_unknown_target",
            errors=unknown,
        )
    chosen_g, chosen_r = set(gremien), set(roles)
    targets = group_targets(snap)
    removed = [
        g for g, (gs, rs) in targets.items() if gs & chosen_g or rs & chosen_r
    ]
    missing_g: set[UUID] = set()
    missing_r: set[UUID] = set()
    for g in removed:
        gs, rs = targets[g]
        missing_g |= gs - chosen_g
        missing_r |= rs - chosen_r
    if missing_g or missing_r:
        raise ValidationProblem(
            "A removed SSO group also leads to an entry that is not selected.",
            code="revoke_incomplete",
            errors=[FieldError(field="gremiumIds", msg=str(g)) for g in sorted(missing_g, key=str)]
            + [
                FieldError(field="globalRoleIds", msg=str(r))
                for r in sorted(missing_r, key=str)
            ],
        )
    assignments = [
        a
        for a in snap.assignments
        if (a.gremium_id is not None and a.gremium_id in chosen_g)
        or (a.gremium_id is None and a.role.id in chosen_r)
    ]
    in_chosen = [d for d in snap.delegations if d.gremium_id in chosen_g]
    return RevokePlan(
        gremium_ids=gremien,
        global_role_ids=roles,
        removed_groups=_ordered_groups(snap, removed),
        assignments=assignments,
        pool=[p for p in snap.pool if p.gremium_id in chosen_g],
        delegations=[d for d in in_chosen if d.meeting_status == _PLANNED],
        kept_live=sum(1 for d in in_chosen if d.meeting_status == _LIVE),
    )


def last_login_filter(before: date | None, include_never: bool) -> ColumnElement[bool] | None:
    """The WHERE clause of the user-list filter "Letzter Login".

    ``before`` keeps the people whose last login is before that day (UTC);
    ``include_never`` adds the people who never logged in. Without ``before``,
    ``include_never`` keeps only those. Neither gives None (no filter).
    """
    never = PrincipalRow.last_login.is_(None)
    if before is not None:
        older = PrincipalRow.last_login < datetime.combine(before, time.min, tzinfo=UTC)
        return older | never if include_never else older
    return never if include_never else None


def has_groups_filter(has_groups: bool | None) -> ColumnElement[bool] | None:
    """The WHERE clause of the user-list filter "Hat SSO-Gruppen" (None: no filter).

    ``oidc_groups`` can be SQL NULL, a JSON ``null`` or an array, so the length is read
    only for an array (a CASE, because SQL does not short-circuit an AND).
    """
    if has_groups is None:
        return None
    col = PrincipalRow.oidc_groups
    length = case(
        (func.jsonb_typeof(col) == "array", func.jsonb_array_length(col)), else_=0
    )
    return length > 0 if has_groups else length == 0


async def principals_with_access(session: AsyncSession, ids: list[UUID]) -> set[UUID]:
    """The principals of ``ids`` that have something a revoke can take away.

    That is a gremium membership, a role assignment other than ``member``, a pool entry
    or a delegation in a planned or live meeting. The OIDC groups are on the row, so the
    caller adds them. One UNION query.
    """
    if not ids:
        return set()
    active_meeting = Meeting.status.in_((_PLANNED, _LIVE))
    stmts: list[Select[Any]] = [
        select(GremiumMembership.principal_id).where(GremiumMembership.principal_id.in_(ids)),
        select(RoleAssignment.principal_id)
        .join(Role, Role.id == RoleAssignment.role_id)
        .where(RoleAssignment.principal_id.in_(ids), Role.key != IMPLICIT_ROLE_KEY),
        *pool_principals_stmt(ids),
        select(MeetingDelegation.delegator_principal_id)
        .join(Meeting, Meeting.id == MeetingDelegation.meeting_id)
        .where(MeetingDelegation.delegator_principal_id.in_(ids), active_meeting),
        select(MeetingDelegation.delegate_principal_id)
        .join(Meeting, Meeting.id == MeetingDelegation.meeting_id)
        .where(MeetingDelegation.delegate_principal_id.in_(ids), active_meeting),
    ]
    rows = (await session.execute(union(*stmts))).scalars().all()
    return {r for r in rows if r is not None}


# -- Service ------------------------------------------------------------------------


def _role(row: Any) -> RoleInfo:  # noqa: ANN401 - a Role or a GremiumRole row
    return RoleInfo(id=row.id, key=row.key, label=dict(row.name_i18n or {}))


class PrincipalRevokeService:
    """Preview and run the revoke of the rights of one person."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _principal(self, principal_id: UUID, *, lock: bool) -> PrincipalRow:
        """Load the principal (``FOR UPDATE`` with ``lock``).

        Raises:
            NotFoundError: No principal has this id (404).
            ConflictError: The account is merged (``principal_merged``) (409).
        """
        stmt = select(PrincipalRow).where(PrincipalRow.id == principal_id)
        if lock:
            stmt = stmt.with_for_update()
        row = (await self.session.scalars(stmt)).first()
        if row is None:
            raise NotFoundError(f"principal {principal_id} not found")
        if row.merged_into is not None:
            raise ConflictError(
                "A merged account holds no rights.", code="principal_merged"
            )
        return row

    async def _snapshot(self, row: PrincipalRow) -> Snapshot:
        """Load everything that ties the principal to a Gremium or a global role."""
        s = self.session
        pid = row.id
        snap = Snapshot(principal_id=pid, groups=[str(g) for g in (row.oidc_groups or [])])
        for membership, grole in (
            await s.execute(
                select(GremiumMembership, GremiumRole)
                .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
                .where(GremiumMembership.principal_id == pid)
            )
        ).all():
            snap.memberships.append(MembershipFact(membership.gremium_id, _role(grole)))
        for assignment, role in (
            await s.execute(
                select(RoleAssignment, Role)
                .join(Role, Role.id == RoleAssignment.role_id)
                .where(RoleAssignment.principal_id == pid)
            )
        ).all():
            snap.assignments.append(
                AssignmentFact(
                    id=assignment.id,
                    role=_role(role),
                    gremium_id=assignment.gremium_id,
                    granted_by=assignment.granted_by,
                    valid_from=assignment.valid_from,
                    valid_until=assignment.valid_until,
                )
            )
        snap.pool = [
            PoolFact(p.id, p.gremium_id, p.member_principal_id, p.substitute_principal_id)
            for p in await pool_entries_of(s, pid)
        ]
        for d, meeting in (
            await s.execute(
                select(MeetingDelegation, Meeting)
                .join(Meeting, Meeting.id == MeetingDelegation.meeting_id)
                .where(
                    (MeetingDelegation.delegator_principal_id == pid)
                    | (MeetingDelegation.delegate_principal_id == pid),
                    Meeting.status.in_((_PLANNED, _LIVE)),
                )
            )
        ).all():
            snap.delegations.append(
                DelegationFact(
                    id=d.id,
                    gremium_id=d.gremium_id,
                    meeting_id=meeting.id,
                    meeting_title=meeting.title,
                    meeting_date=meeting.date,
                    meeting_status=meeting.status,
                    delegator_id=d.delegator_principal_id,
                    delegate_id=d.delegate_principal_id,
                    voting=bool(d.delegate_voting),
                )
            )
        if snap.groups:
            await self._load_mappings(snap)
        tied = tied_gremien(snap)
        if tied:
            snap.gremium_names = {
                gid: name
                for gid, name in (
                    await s.execute(select(Gremium.id, Gremium.name).where(Gremium.id.in_(tied)))
                ).all()
            }
        others = {p.substitute_id for p in snap.pool} | {
            p.member_id for p in snap.pool if p.member_id is not None
        }
        others |= {d.delegator_id for d in snap.delegations}
        others |= {d.delegate_id for d in snap.delegations}
        others.discard(pid)
        snap.names = {i: ref.name for i, ref in (await refs_by_id(s, others)).items()}
        grantors = {a.granted_by for a in snap.assignments if a.granted_by}
        snap.grantor_names = {
            sub: ref.name for sub, ref in (await refs_by_sub(s, grantors)).items()
        }
        snap.open_tasks = await self._open_tasks(
            row.sub, {m.gremium_id for m in snap.memberships}
        )
        return snap

    async def _load_mappings(self, snap: Snapshot) -> None:
        """Load the three mappings of the person's groups into the snapshot."""
        s = self.session
        snap.membership_maps = [
            (str(group), gid)
            for group, gid in (
                await s.execute(
                    select(
                        GremiumMembershipMapping.oidc_group, GremiumMembershipMapping.gremium_id
                    ).where(GremiumMembershipMapping.oidc_group.in_(snap.groups))
                )
            ).all()
        ]
        snap.role_maps = [
            (str(group), gid, rid)
            for group, gid, rid in (
                await s.execute(
                    select(GremiumRoleMapping.oidc_group, GremiumRole.gremium_id, GremiumRole.id)
                    .join(GremiumRole, GremiumRole.id == GremiumRoleMapping.gremium_role_id)
                    .where(GremiumRoleMapping.oidc_group.in_(snap.groups))
                )
            ).all()
        ]
        snap.group_maps = [
            (str(group), _role(role))
            for group, role in (
                await s.execute(
                    select(GroupMapping.oidc_group, Role)
                    .join(Role, Role.id == GroupMapping.role_id)
                    .where(GroupMapping.oidc_group.in_(snap.groups))
                )
            ).all()
        ]

    async def _open_tasks(self, sub: str, gremien: set[UUID]) -> dict[UUID, int]:
        """Count the open votes per Gremium that still wait for a ballot of ``sub``.

        A vote names its Gremium in ``eligible_group``. A ballot or a voted marker of
        ``sub`` means the person already voted.
        """
        if not gremien:
            return {}
        by_key = {str(g): g for g in gremien}
        rows = (
            await self.session.execute(
                select(Vote.eligible_group, func.count(Vote.id))
                .where(
                    Vote.status == "open",
                    Vote.eligible_group.in_(by_key),
                    ~exists().where(Ballot.vote_id == Vote.id, Ballot.voter_sub == sub),
                    ~exists().where(VotedMarker.vote_id == Vote.id, VotedMarker.voter_sub == sub),
                )
                .group_by(Vote.eligible_group)
            )
        ).all()
        return {by_key[key]: int(count) for key, count in rows if key in by_key}

    async def preview(self, principal_id: UUID, *, actor: str) -> RevokePreviewOut:
        """List what the person has, per Gremium and per global role. Writes nothing.

        Raises:
            NotFoundError: No principal has this id (404).
            ConflictError: The account is merged (``principal_merged``) (409).
        """
        row = await self._principal(principal_id, lock=False)
        snap = await self._snapshot(row)
        return build_preview(snap, row, is_self=row.sub == actor)

    async def revoke(
        self, principal_id: UUID, payload: PrincipalRevokeIn, *, actor: str
    ) -> tuple[RevokeResultOut, list[DelegationMailInfo | None]]:
        """Clear the selected Gremien and global roles in one transaction and commit.

        Returns the result and the mail data of the revoked delegations (collected
        before the delete), so the caller can mail the delegates after the commit.

        Raises:
            NotFoundError: No principal has this id (404).
            ConflictError: The own account (``revoke_own_account``) or a merged
                account (``principal_merged``) (409).
            ValidationProblem: See ``plan_revoke`` (422).
        """
        try:
            row = await self._principal(principal_id, lock=True)
            if row.sub == actor:
                raise ConflictError(
                    "You cannot revoke the rights of your own account.",
                    code="revoke_own_account",
                )
            snap = await self._snapshot(row)
            plan = plan_revoke(
                snap,
                payload.gremium_ids,
                payload.global_role_ids,
                deactivate=payload.deactivate,
            )
            mails = [
                await meeting_delegation_mail_info(self.session, d.id) for d in plan.delegations
            ]
            deactivated = await self._apply(row, plan, actor, deactivate=payload.deactivate)
            await self.session.commit()
        except BaseException:
            await self.session.rollback()
            raise
        return (
            RevokeResultOut(
                gremium_ids=plan.gremium_ids,
                global_role_ids=plan.global_role_ids,
                removed_groups=plan.removed_groups,
                deleted_assignments=len(plan.assignments),
                deleted_pool_entries=len(plan.pool),
                revoked_delegations=len(plan.delegations),
                kept_live_delegations=plan.kept_live,
                deactivated=deactivated,
            ),
            mails,
        )

    async def _apply(
        self, row: PrincipalRow, plan: RevokePlan, actor: str, *, deactivate: bool
    ) -> bool:
        """Write the plan. Does not commit. Returns True when it deactivated the account."""
        s = self.session
        audit = AuditService(s)
        if plan.removed_groups:
            gone = set(plan.removed_groups)
            # A new list, so the JSONB column registers the change.
            row.oidc_groups = [g for g in (row.oidc_groups or []) if str(g) not in gone]
        if plan.assignments:
            await s.execute(
                delete(RoleAssignment).where(
                    RoleAssignment.id.in_([a.id for a in plan.assignments])
                )
            )
        if plan.pool:
            await s.execute(
                delete(DelegationSubstitute).where(
                    DelegationSubstitute.id.in_([p.id for p in plan.pool])
                )
            )
        for d in plan.delegations:
            await s.execute(delete(MeetingDelegation).where(MeetingDelegation.id == d.id))
            # The same entry as the revoke route writes, plus the marker of this path.
            await audit.record(
                actor=actor,
                action=AuditAction.DELEGATION_REVOKE,
                target_type="meeting_delegation",
                target_id=str(d.id),
                data={
                    "meetingId": str(d.meeting_id),
                    "delegatorId": str(d.delegator_id),
                    "byAccessRevoke": True,
                },
            )
        await s.flush()
        await sync_principal_memberships(s, row)
        deactivated = deactivate and row.active is not False
        if deactivated:
            # The existing deactivation path (`set_principal_active`) writes this entry.
            row.active = False
            await audit.record(
                actor=actor,
                action=AuditAction.ROLE_CHANGE,
                target_type="principal",
                target_id=str(row.id),
            )
        await audit.record(
            actor=actor,
            action=AuditAction.PRINCIPAL_ACCESS_REVOKE,
            target_type="principal",
            target_id=str(row.id),
            data={
                "gremiumIds": [str(g) for g in plan.gremium_ids],
                "globalRoleIds": [str(r) for r in plan.global_role_ids],
                "removedGroups": plan.removed_groups,
                "assignmentIds": [str(a.id) for a in plan.assignments],
                "poolEntryIds": [str(p.id) for p in plan.pool],
                "delegationIds": [str(d.id) for d in plan.delegations],
                "keptLiveDelegations": plan.kept_live,
                "deactivate": deactivate,
            },
        )
        return deactivated


__all__ = [
    "IMPLICIT_ROLE_KEY",
    "AssignmentFact",
    "DelegationFact",
    "MembershipFact",
    "PoolFact",
    "PrincipalRevokeService",
    "RevokePlan",
    "RoleInfo",
    "Snapshot",
    "build_preview",
    "group_targets",
    "has_groups_filter",
    "held_roles",
    "last_login_filter",
    "plan_revoke",
    "principals_with_access",
    "tied_gremien",
]
